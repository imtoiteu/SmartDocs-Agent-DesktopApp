"""SummarizeTranslateSkill — summarize text, then translate the summary.

Orchestrates two existing tools (summarize → translate). No new business logic.
"""

from __future__ import annotations

from typing import Any

from .base import Skill, SkillContext, SkillResult


class SummarizeTranslateSkill(Skill):
    name = "summarize_translate"
    description = (
        "Summarize the given text and, if a target language is given, also "
        "translate the summary into it. With no target language it summarizes "
        "only. Orchestrates the 'summarize' then (optionally) 'translate' tools."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to summarize and (optionally) translate."},
            "to_lang": {"type": "string",
                        "description": "Target language code for the summary; omit to summarize only.",
                        "default": ""},
            "mode": {"type": "string", "enum": ["short", "bullets", "executive"], "default": "short"},
            "summary_mode": {"type": "string", "enum": ["fast", "ai_rewrite"], "default": "fast"},
        },
        "required": ["text"],
    }

    def run(self, ctx: SkillContext, *, text: str, to_lang: str = "",
            mode: str = "short", summary_mode: str = "fast", **_: Any) -> SkillResult:
        s = ctx.tools.run("summarize", text=text, mode=mode, summary_mode=summary_mode)
        steps = [{"tool": "summarize", "ok": s.ok, "meta": s.meta}]
        if not s.ok:
            return SkillResult.failure(f"summarize failed: {s.error}", steps=steps)

        summary = s.data.get("summary", "")
        # Translation is optional: with no target language this is a summarize-only
        # run, so a user can summarize a document without also translating it.
        if not (to_lang or "").strip():
            return SkillResult.success({"summary": summary}, steps=steps)

        t = ctx.tools.run("translate", text=summary, to_lang=to_lang)
        steps.append({"tool": "translate", "ok": t.ok, "meta": t.meta})
        if not t.ok:
            # Partial result: the summary still succeeded.
            return SkillResult.failure(
                f"translate failed: {t.error}",
                data={"summary": summary, "to_lang": to_lang}, steps=steps,
            )

        return SkillResult.success(
            {"summary": summary, "translated_summary": t.data.get("translated", ""), "to_lang": to_lang},
            steps=steps,
        )
