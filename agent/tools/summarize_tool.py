"""Summarize Tool — wraps ``services.summary_service.summarize``.

The service handles language auto-routing (English TextRank / Vietnamese PhoBERT)
and the optional abstractive AI-rewrite pass. The tool adds no summarization
logic.
"""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolResult


class SummarizeTool(Tool):
    name = "summarize"
    description = (
        "Summarize text. 'summary_mode'=fast is extractive (TextRank/PhoBERT); "
        "'ai_rewrite' adds an abstractive Qwen pass. 'mode' shapes the output "
        "(short paragraph, bullets, or executive summary)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to summarize."},
            "mode": {
                "type": "string",
                "description": "Output shape.",
                "enum": ["short", "bullets", "executive"],
                "default": "short",
            },
            "engine": {
                "type": "string",
                "description": "Extractive engine selector.",
                "enum": ["auto", "fast", "smart"],
                "default": "auto",
            },
            "summary_mode": {
                "type": "string",
                "description": "Pipeline mode: extractive only, or extractive + AI rewrite.",
                "enum": ["fast", "ai_rewrite"],
                "default": "fast",
            },
        },
        "required": ["text"],
    }

    def run(self, text: str, mode: str = "short", engine: str = "auto",
            summary_mode: str = "fast", **_: Any) -> ToolResult:
        from services import summary_service

        res = summary_service.summarize(
            text, mode=mode, engine=engine, summary_mode=summary_mode
        )
        return ToolResult.success(
            res,
            engine=res.get("engine_used"),
            lang=res.get("lang"),
            summarize_elapsed_ms=res.get("elapsed_ms"),
        )
