from __future__ import annotations

import time

from .base import OCREngine


class PaddleOCREngine(OCREngine):
    """Adapter around the existing PaddleOCR implementation."""

    engine_name = "paddleocr"

    def __init__(self):
        self._ocr = None

    def _get_ocr(self):
        if self._ocr is None:
            from ._paddle_guard import disable_paddle_signal_handler
            disable_paddle_signal_handler()  # before Paddle init (Paddle+Torch coexist)
            from paddleocr import PaddleOCR

            # Pin to PP-OCRv5 so this "Legacy" engine stays byte-for-byte unchanged
            # after the 3.7 upgrade (whose default pipeline is otherwise PP-OCRv6).
            self._ocr = PaddleOCR(
                ocr_version="PP-OCRv5",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
            )
        return self._ocr

    def run(self, image_path: str) -> dict:
        from PIL import Image

        img = Image.open(image_path)
        w, h = img.size
        t0 = time.time()
        raw = self._get_ocr().predict(image_path)
        ms = round((time.time() - t0) * 1000)

        items = []
        for res in raw:
            texts = res.get("rec_texts", [])
            scores = res.get("rec_scores", [])
            boxes = res.get("det_polys", res.get("dt_polys", []))
            for i, text in enumerate(texts):
                sc = float(scores[i]) if i < len(scores) else None
                bx = boxes[i].tolist() if i < len(boxes) else None
                items.append(
                    {
                        "text": text,
                        "confidence": round(sc, 4) if sc else None,
                        "box": bx,
                    }
                )

        return {
            "success": True,
            "results": items,
            "img_width": w,
            "img_height": h,
            "elapsed_ms": ms,
            "ocr_engine": self.engine_name,
            "inference_status": "ok",
        }
