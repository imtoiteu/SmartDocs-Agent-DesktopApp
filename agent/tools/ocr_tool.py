"""OCR Tool — wraps ``services.smart_ocr_service.run_ocr_pipeline``.

``run_ocr_pipeline`` already composes the existing stack: the OCR engine router
(legacy paddle / vietocr / paddleocr_modern / glmocr) + layout reconstruction,
and optional Qwen line-level AI cleanup. The tool adds no OCR logic; it only
adapts inputs/outputs into the uniform tool contract.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import Tool, ToolResult


class OcrTool(Tool):
    name = "ocr"
    description = (
        "Run OCR on a single image file (e.g. an uploaded picture or a "
        "pre-rendered PDF page) and return the extracted text, per-line results "
        "with bounding boxes and confidence, and — for layout-aware engines — "
        "markdown/html/tables/layout blocks. Engines: 'paddle' (legacy PP-OCRv5), "
        "'vietocr' (Vietnamese), 'paddleocr_modern' (PP-StructureV3), 'glmocr'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Absolute path to an image file on disk to run OCR on.",
            },
            "engine": {
                "type": "string",
                "description": "OCR engine to use. Omit to use the configured default.",
                "enum": ["paddle", "vietocr", "paddleocr_modern", "glmocr"],
            },
            "apply_ai": {
                "type": "boolean",
                "description": "Apply Qwen AI line-level cleanup to the OCR text (slower, optional).",
                "default": False,
            },
        },
        "required": ["image_path"],
    }

    def run(self, image_path: str, engine: Optional[str] = None,
            apply_ai: bool = False, **_: Any) -> ToolResult:
        from services import smart_ocr_service

        res = smart_ocr_service.run_ocr_pipeline(
            image_path, engine_name=engine, apply_ai=apply_ai
        )
        if not res:
            return ToolResult.failure("OCR returned no result", engine=engine)
        if res.get("success") is False:
            return ToolResult.failure(res.get("error", "OCR failed"),
                                      engine=res.get("ocr_engine") or engine)
        return ToolResult.success(
            res,
            engine=res.get("ocr_engine") or res.get("smart_engine") or engine,
            ocr_elapsed_ms=res.get("elapsed_ms"),
            smart_applied=res.get("smart_applied", False),
            layout_native=res.get("layout_native", False),
        )
