from __future__ import annotations

import logging
import time

from .base import OCREngine

logger = logging.getLogger(__name__)


def _to_native(obj):
    """Best-effort conversion of numpy/array-likes to JSON-serialisable python types."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "tolist"):
        try:
            return obj.tolist()
        except Exception:
            pass
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    return obj


def _esc(s: str) -> str:
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# Layout label → HTML tag, used to render a simple structured HTML representation.
_HEADING_LABELS = {"doc_title", "title"}
_SUBHEADING_LABELS = {"paragraph_title", "figure_title", "chart_title", "table_title"}


def _blocks_to_html(blocks: list, tables_html: list) -> str:
    """Build a lightweight HTML document from PP-StructureV3 parsing blocks.

    Table blocks usually carry their HTML in ``table_res_list`` (not in block_content),
    so table-labelled blocks consume from the tables queue in reading order; everything
    else is wrapped by a tag chosen from the block label. Best-effort, never raises.
    """
    parts = []
    table_q = list(tables_html or [])
    for b in blocks:
        label = (b.get("block_label") or "text").lower()
        content = str(b.get("block_content") or "")
        if "table" in label:
            if "<table" in content.lower():
                parts.append(content)            # inline HTML already present
            elif table_q:
                parts.append(table_q.pop(0))     # pull the next detected table
            continue
        if not content.strip():
            continue
        if label in _HEADING_LABELS:
            parts.append(f"<h1>{_esc(content)}</h1>")
        elif label in _SUBHEADING_LABELS:
            parts.append(f"<h2>{_esc(content)}</h2>")
        elif label in ("formula", "equation"):
            parts.append(f"<pre class='formula'>{_esc(content)}</pre>")
        elif label in ("image", "figure", "chart"):
            continue                             # no inline image text
        else:
            parts.append(f"<p>{_esc(content)}</p>")
    # Any tables not matched to a block (e.g. table-only pages) are appended.
    parts.extend(table_q)
    return "\n".join(parts)


_LABEL_COLORS = {
    "text": (66, 133, 244), "paragraph_title": (219, 68, 55),
    "doc_title": (219, 68, 55), "table": (15, 157, 88),
    "figure": (244, 160, 0), "image": (244, 160, 0),
    "formula": (171, 71, 188), "table_title": (15, 157, 88),
}


def _render_layout_overlay(image_path: str, blocks: list) -> str | None:
    """Draw labelled, reading-order-numbered region boxes on the page image and
    return a base64 PNG data URI. Best-effort — returns None on any failure.

    This is the Modern engine's "Extracted Images" artifact: unlike the live canvas
    overlay it shows the *reading order* (1,2,3…) and the *region label* per block,
    which is exactly the layout interpretation a user wants to inspect.
    """
    try:
        import base64
        from io import BytesIO
        from PIL import Image, ImageDraw, ImageFont

        im = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(im, "RGBA")
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
        n = 0
        for b in blocks:
            bbox = b.get("bbox")
            if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
                continue
            try:
                x0, y0, x1, y1 = (float(v) for v in bbox)
            except Exception:
                continue
            n += 1
            label = (b.get("label") or "text").lower()
            color = _LABEL_COLORS.get(label, (120, 120, 120))
            draw.rectangle([x0, y0, x1, y1], outline=color + (255,), width=3)
            draw.rectangle([x0, y0, x1, y1], fill=color + (28,))
            tag = f"{n} {label}"
            tw = (draw.textlength(tag, font=font) if font else 8 * len(tag))
            draw.rectangle([x0, max(0, y0 - 16), x0 + tw + 8, y0], fill=color + (235,))
            draw.text((x0 + 4, max(0, y0 - 15)), tag, fill=(255, 255, 255), font=font)
        if n == 0:
            return None
        buf = BytesIO()
        im.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


class PaddleOCRModernEngine(OCREngine):
    """PaddleOCR Modern — PP-StructureV3 document pipeline.

    Returns the SAME standard shape as the other engines (``results`` = list of
    ``{text, confidence, box}`` from the underlying OCR pass) so the canvas overlay,
    box geometry and the plain-text flatten path keep working unchanged. In addition
    it attaches structured representations the legacy engines cannot produce:
    ``markdown``, ``html``, ``tables_html`` and ``layout_blocks``. ``layout_native``
    tells ``ocr_service.run_ocr`` to skip the geometric reading-order reconstruction
    (PP-StructureV3 already returns blocks in reading order).
    """

    engine_name = "paddleocr_modern"

    def __init__(self):
        self._pipe = None

    def _get_pipe(self):
        if self._pipe is None:
            from ._paddle_guard import disable_paddle_signal_handler
            disable_paddle_signal_handler()  # before Paddle init (Paddle+Torch coexist)
            from paddleocr import PPStructureV3

            # Document preprocessing (orientation + UVDoc unwarping) is ON: PP-StructureV3's
            # table-structure model assigns cells to a grid geometrically, so perspective
            # skew in PHOTOS scrambles rows/columns (dropped headers, mis-paired values).
            # Dewarping rectifies the page first and fixes the table structure. The OCR boxes
            # then live in the rectified space, so run() also returns that rectified image as
            # the canvas background (page_image_b64) to keep the overlay aligned.
            # PP-StructureV3 defaults its OCR sub-pipeline to PP-OCRv5_server; pin it to
            # PP-OCRv6_medium so "Modern" actually uses the newest recognition models.
            self._pipe = PPStructureV3(
                use_doc_orientation_classify=True,
                use_doc_unwarping=True,
                use_seal_recognition=False,
                use_chart_recognition=False,
                text_detection_model_name="PP-OCRv6_medium_det",
                text_recognition_model_name="PP-OCRv6_medium_rec",
            )
        return self._pipe

    def run(self, image_path: str) -> dict:
        from PIL import Image

        img = Image.open(image_path)
        w, h = img.size

        t0 = time.time()
        page_results = list(self._get_pipe().predict(image_path))
        ms = round((time.time() - t0) * 1000)

        items: list[dict] = []
        markdown_parts: list[str] = []
        tables_html: list[str] = []
        layout_blocks: list[dict] = []
        for res in page_results:
            try:
                j = res.json or {}
            except Exception:
                j = {}
            # `res.json` may itself be wrapped as {"res": {...}} depending on version.
            if isinstance(j, dict) and "res" in j and isinstance(j["res"], dict):
                j = j["res"]

            # --- standard results from the underlying OCR pass (canvas + flatten) ---
            ocr = j.get("overall_ocr_res", {}) or {}
            texts = ocr.get("rec_texts", []) or []
            scores = ocr.get("rec_scores", []) or []
            polys = ocr.get("rec_polys", ocr.get("dt_polys", [])) or []
            for i, text in enumerate(texts):
                sc = float(scores[i]) if i < len(scores) and scores[i] is not None else None
                box = _to_native(polys[i]) if i < len(polys) else None
                items.append({
                    "text": text,
                    "confidence": round(sc, 4) if sc else None,
                    "box": box,
                })

            # --- markdown ---
            try:
                md = res.markdown
                md_text = md.get("markdown_texts", "") if isinstance(md, dict) else ""
                if md_text:
                    markdown_parts.append(md_text)
            except Exception:
                pass

            # --- tables (HTML) ---
            for t in (j.get("table_res_list", []) or []):
                html = t.get("pred_html") if isinstance(t, dict) else None
                if html:
                    tables_html.append(str(html))

            # --- layout blocks (label/content/bbox/order) ---
            for b in (j.get("parsing_res_list", []) or []):
                if not isinstance(b, dict):
                    continue
                layout_blocks.append({
                    "label":   b.get("block_label"),
                    "content": b.get("block_content"),
                    "bbox":    _to_native(b.get("block_bbox")),
                    "order":   b.get("block_order"),
                })

        # Reading order: prefer PP-StructureV3's block_order; when it is missing (some
        # versions/paths leave it None), fall back to geometric order (top→bottom, then
        # left→right) instead of trusting raw list order. Stable sort keeps ties as-is.
        def _order_key(b):
            o = b.get("order")
            bbox = b.get("bbox") or [0, 0, 0, 0]
            try:
                y0, x0 = float(bbox[1]), float(bbox[0])
            except Exception:
                y0, x0 = 0.0, 0.0
            return (0, float(o), 0.0) if isinstance(o, (int, float)) else (1, y0, x0)

        layout_blocks.sort(key=_order_key)

        markdown = "\n\n".join(p for p in markdown_parts if p.strip())
        html = _blocks_to_html(layout_blocks, tables_html)

        # Extracted Images: a labelled, reading-order-numbered layout overlay so the
        # viewer's gallery can show how PP-StructureV3 interpreted the page.
        images = []
        overlay = _render_layout_overlay(image_path, layout_blocks)
        if overlay:
            images.append({"label": "layout", "kind": "layout", "page": 1, "src": overlay})

        return {
            "success": True,
            "results": items,
            "img_width": w,
            "img_height": h,
            "elapsed_ms": ms,
            "ocr_engine": self.engine_name,
            "inference_status": "ok",
            "layout_native": True,           # skip geometric reconstruction in ocr_service
            "markdown": markdown,
            "html": html,
            "tables_html": tables_html,
            "layout_blocks": layout_blocks,
            "images": images,
        }
