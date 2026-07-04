from __future__ import annotations

from config import cfg

from .glm_adapter import GLMOCREngine
from .paddle_adapter import PaddleOCREngine
from .paddle_modern_adapter import PaddleOCRModernEngine
from .vietocr_adapter import VietOCREngine

_ENGINES = {
    "paddleocr": PaddleOCREngine(),
    "vietocr": VietOCREngine(),
    "paddleocr_modern": PaddleOCRModernEngine(),
    "glmocr": GLMOCREngine(),
}
_ALIASES = {
    "paddle": "paddleocr",
    "paddleocr": "paddleocr",
    "vietocr": "vietocr",
    "paddleocr_modern": "paddleocr_modern",
    "modern": "paddleocr_modern",
    "ppstructure": "paddleocr_modern",
    "glmocr": "glmocr",
    "glm": "glmocr",
    "glm_ocr": "glmocr",
    "auto": "paddleocr",  # Explicitly allow 'auto' alias
}
_DEFAULT_ENGINE = _ALIASES.get(cfg.OCR_ENGINE, "paddleocr")
_ALIASES["auto"] = _DEFAULT_ENGINE  # Map auto to whatever the configured default is


def normalize_engine_name(engine_name: str | None = None) -> str:
    raw = (engine_name or _DEFAULT_ENGINE).lower().strip()
    if raw not in _ALIASES:
        raise ValueError(f"Unsupported OCR engine: {engine_name}")
    return _ALIASES[raw]


def default_engine_name() -> str:
    return _DEFAULT_ENGINE


def available_engines() -> list[str]:
    return list(_ENGINES.keys())


def get_engine(engine_name: str | None = None):
    name = normalize_engine_name(engine_name)
    return _ENGINES[name]


def run_ocr(image_path: str, engine_name: str | None = None) -> dict:
    return get_engine(engine_name).run(image_path)
