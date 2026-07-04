"""TranslateSkill — translate text into a target language. A thin, single-tool action.

Exposes translation as a standalone action (not only the translate-the-summary
step of summarize_translate), wrapping the existing 'translate' tool. No new logic.
"""

from __future__ import annotations

from typing import Any

from .base import Skill, SkillContext, SkillResult


class TranslateSkill(Skill):
    name = "translate"
    description = "Translate the given text into a target language."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to translate."},
            "to_lang": {"type": "string", "description": "Target language code (e.g. 'vi', 'en')."},
            "from_lang": {"type": "string", "description": "Source language code, or 'auto'.",
                          "default": "auto"},
        },
        "required": ["text", "to_lang"],
    }

    def run(self, ctx: SkillContext, *, text: str, to_lang: str,
            from_lang: str = "auto", **_: Any) -> SkillResult:
        t = ctx.tools.run("translate", text=text, to_lang=to_lang, from_lang=from_lang)
        steps = [{"tool": "translate", "ok": t.ok, "meta": t.meta}]
        if not t.ok:
            return SkillResult.failure(f"translate failed: {t.error}", steps=steps)
        return SkillResult.success(
            {"translated": t.data.get("translated", ""), "to_lang": to_lang}, steps=steps)
