from __future__ import annotations

import time
from pathlib import Path

from config import cfg

from .base import OCREngine


class VietOCREngine(OCREngine):
    """
    Image-first VietOCR integration.

    Phase 2 uses PaddleOCR detection boxes plus VietOCR recognition for image
    files. PDF requests should continue using PaddleOCR via the caller.
    """

    engine_name = "vietocr"

    def __init__(self):
        self._detector = None
        self._predictor = None

    def _get_detector(self):
        if self._detector is None:
            from ._paddle_guard import disable_paddle_signal_handler
            disable_paddle_signal_handler()  # before Paddle init (Paddle+Torch coexist)
            from paddleocr import PaddleOCR

            # Pin detection to PP-OCRv5 so VietOCR's detection boxes stay unchanged
            # after the 3.7 upgrade (whose default pipeline is otherwise PP-OCRv6).
            self._detector = PaddleOCR(
                ocr_version="PP-OCRv5",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
            )
        return self._detector

    def _get_predictor(self):
        if self._predictor is None:
            from config import validate_vietocr_config
            from vietocr.tool.config import Cfg
            from vietocr.tool.predictor import Predictor

            # Fully Offline Implementation: Load from local config.yml.
            # Validate BEFORE handing the file to vietocr — Cfg.load_config_from_file
            # does dict.update(yaml.safe_load(f)), so an empty/invalid file crashes
            # with the useless "'NoneType' object is not iterable". Fail with the
            # actual problem and the exact fix instead.
            config_path = cfg.MODEL_DIR / "vietocr" / "config.yml"
            ok, why = validate_vietocr_config(config_path)
            if not ok:
                raise RuntimeError(
                    f"VietOCR config invalid at {config_path}: {why}. "
                    "Run 'scripts/setup_offline.sh' (online, once) to regenerate it, "
                    "or set VIETOCR_CONFIG/VIETOCR_WEIGHTS."
                )

            config = Cfg.load_config_from_file(str(config_path))

            # Use local weights and disable internet-based pretrained loading
            config["cnn"]["pretrained"] = False
            config["device"] = cfg.VIETOCR_DEVICE
            config["predictor"]["beamsearch"] = False

            # Explicitly set local weights path
            if cfg.VIETOCR_WEIGHTS:
                config["weights"] = cfg.VIETOCR_WEIGHTS
            else:
                # Default to vgg_transformer.pth in the same directory
                config["weights"] = str(cfg.MODEL_DIR / "vietocr" / "vgg_transformer.pth")

            weights = str(config["weights"])
            if not weights.startswith("http") and not Path(weights).exists():
                raise RuntimeError(
                    f"VietOCR weights missing at {weights}. "
                    "Run 'scripts/setup_offline.sh' (online, once) to download them."
                )

            self._predictor = Predictor(config)
        return self._predictor

    @staticmethod
    def _crop_polygon(image, polygon):
        xs = [int(pt[0]) for pt in polygon]
        ys = [int(pt[1]) for pt in polygon]
        left, top = max(0, min(xs)), max(0, min(ys))
        right, bottom = max(xs), max(ys)
        if right <= left or bottom <= top:
            return None
        return image.crop((left, top, right, bottom))

    def run(self, image_path: str) -> dict:
        from PIL import Image

        suffix = Path(image_path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise ValueError("VietOCR currently supports image OCR only in this phase.")

        image = Image.open(image_path).convert("RGB")
        w, h = image.size
        t0 = time.time()

        detector = self._get_detector()
        predictor = self._get_predictor()
        # Paddle's predict() can return None on some inputs — never iterate None.
        detected = detector.predict(image_path) or []

        items = []
        for res in detected:
            boxes = res.get("det_polys", res.get("dt_polys", []))
            for poly in boxes:
                polygon = poly.tolist() if hasattr(poly, "tolist") else poly
                crop = self._crop_polygon(image, polygon)
                if crop is None:
                    continue
                try:
                    text = predictor.predict(crop)
                except Exception:
                    text = ""
                items.append(
                    {
                        "text": text,
                        "confidence": None,
                        "box": polygon,
                    }
                )

        ms = round((time.time() - t0) * 1000)
        return {
            "success": True,
            "results": items,
            "img_width": w,
            "img_height": h,
            "elapsed_ms": ms,
            "ocr_engine": self.engine_name,
            "inference_status": "ok",
        }
