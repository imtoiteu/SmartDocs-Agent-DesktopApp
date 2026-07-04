import base64
from io import BytesIO
from pathlib import Path

from services.ocr_engines import router
from services import layout_service


DEFAULT_ENGINE = router.default_engine_name()


def pil_to_b64(pil_img, fmt="JPEG"):
    buf = BytesIO()
    pil_img.convert("RGB").save(buf, format=fmt, quality=92)
    return base64.b64encode(buf.getvalue()).decode()


def pdf_page_to_pil(pdf_path, page_num, scale=2.0):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_path)
    bm = doc[page_num - 1].render(scale=scale)
    pil = bm.to_pil()
    doc.close()
    return pil


def pdf_page_count(pdf_path):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_path)
    n = len(doc)
    doc.close()
    return n


def get_default_engine_name() -> str:
    return router.default_engine_name()


def get_available_engines() -> list[str]:
    return router.available_engines()


def normalize_engine_name(engine_name: str | None = None) -> str:
    return router.normalize_engine_name(engine_name)


def run_ocr(image_path: str, engine_name: str | None = None) -> dict:
    """
    Public OCR entry point used by the app.
    Defaults to PaddleOCR and preserves the existing result shape.
    Applies layout reconstruction to naturally order blocks.
    """
    from services import activity_registry
    with activity_registry.track("ocr"):  # DIAGNOSTIC: in-flight CPU-heavy op
        res = router.run_ocr(image_path, engine_name or router.default_engine_name())
    if res and res.get("success") and "results" in res:
        import copy
        res["raw_results"] = copy.deepcopy(res["results"])
        # Engines that already return blocks in reading order (e.g. PaddleOCR Modern /
        # PP-StructureV3) set layout_native=True and opt out of the geometric/LayoutParser
        # reconstruction, which would otherwise reorder their results.
        if not res.get("layout_native"):
            res["results"] = layout_service.reconstruct_layout(
                res["results"],
                res.get("img_width", 0),
                res.get("img_height", 0),
                image=image_path
            )
    return res
