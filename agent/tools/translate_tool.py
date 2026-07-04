"""Translate Tool — wraps ``services.translate_service.translate``.

The service decides online (API) vs offline (Argos) per the ``engine`` argument
and machine connectivity. The tool adds no translation logic.
"""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolResult


class TranslateTool(Tool):
    name = "translate"
    description = (
        "Translate text between languages using the SmartDocs translation "
        "service. Uses an online API when available or offline Argos models; "
        "'engine' forces a specific backend."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to translate."},
            "from_lang": {
                "type": "string",
                "description": "Source language code, or 'auto' to detect.",
                "default": "auto",
            },
            "to_lang": {
                "type": "string",
                "description": "Target language code (e.g. 'vi', 'en').",
                "default": "vi",
            },
            "engine": {
                "type": "string",
                "description": "Translation backend.",
                "enum": ["auto", "online", "offline"],
                "default": "auto",
            },
        },
        "required": ["text"],
    }

    def run(self, text: str, from_lang: str = "auto", to_lang: str = "vi",
            engine: str = "auto", **_: Any) -> ToolResult:
        from services import translate_service

        res = translate_service.translate(
            text, from_lang=from_lang, to_lang=to_lang, engine=engine
        )
        return ToolResult.success(
            res,
            engine=res.get("engine_used"),
            translate_elapsed_ms=res.get("elapsed_ms"),
        )
