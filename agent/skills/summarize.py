"""SummarizeSkill — summarize text. A thin, single-tool action.

Exposes summarization as a standalone action (distinct from the
summarize_translate combo), wrapping the existing 'summarize' tool. Orchestration
only — no new business logic.
"""

from __future__ import annotations

from typing import Any

from .base import Skill, SkillContext, SkillResult


class SummarizeSkill(Skill):
    name = "summarize"
    description = "Summarize the given text (no translation)."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to summarize."},
            "mode": {"type": "string", "enum": ["short", "bullets", "executive"], "default": "short"},
            "summary_mode": {"type": "string", "enum": ["fast", "ai_rewrite"], "default": "fast"},
        },
        "required": ["text"],
    }

    def run(self, ctx: SkillContext, *, text: str, mode: str = "short",
            summary_mode: str = "fast", **_: Any) -> SkillResult:
        s = ctx.tools.run("summarize", text=text, mode=mode, summary_mode=summary_mode)
        steps = [{"tool": "summarize", "ok": s.ok, "meta": s.meta}]
        if not s.ok:
            return SkillResult.failure(f"summarize failed: {s.error}", steps=steps)
        return SkillResult.success({"summary": s.data.get("summary", "")}, steps=steps)
