"""Correction Tool — wraps ``services.correction_service.correct``.

Reuses the existing text-correction capability (whitespace/punctuation cleanup +
English spelling repair via autocorrect). Text-in / text-out: no file paths and
no tenancy, so it is safe to expose in the HTTP-driven agent loop. The tool adds
no correction logic; it only adapts the service call into the uniform contract.
"""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolResult


class CorrectionTool(Tool):
    name = "correct"
    description = (
        "Clean up and correct text: fix spacing and punctuation and repair "
        "obvious English misspellings. Returns the corrected text and a change "
        "count. Useful for tidying raw OCR output before further processing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to correct."},
        },
        "required": ["text"],
    }

    def run(self, text: str, **_: Any) -> ToolResult:
        from services import correction_service

        res = correction_service.correct(text or "")
        return ToolResult.success(
            res,
            changes=res.get("changes"),
            correct_elapsed_ms=res.get("elapsed_ms"),
        )
