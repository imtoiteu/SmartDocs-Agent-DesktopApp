"""CorrectSkill — clean up / correct text. A thin, single-tool action.

Exposes text correction as a standalone action, wrapping the existing 'correct'
tool. Orchestration only — no new business logic.
"""

from __future__ import annotations

from typing import Any

from .base import Skill, SkillContext, SkillResult


class CorrectSkill(Skill):
    name = "correct"
    description = "Clean up and correct the given text (spacing, punctuation, obvious misspellings)."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to correct."},
        },
        "required": ["text"],
    }

    def run(self, ctx: SkillContext, *, text: str, **_: Any) -> SkillResult:
        c = ctx.tools.run("correct", text=text)
        steps = [{"tool": "correct", "ok": c.ok, "meta": c.meta}]
        if not c.ok:
            return SkillResult.failure(f"correct failed: {c.error}", steps=steps)
        return SkillResult.success(
            {"corrected": c.data.get("corrected", ""), "changes": c.data.get("changes")},
            steps=steps)
