"""OcrDigestSkill — OCR an image, summarize the text, optionally translate.

Orchestrates ocr → summarize (→ translate). No new business logic.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import Skill, SkillContext, SkillResult


def _ocr_text(data: dict) -> str:
    """Best-effort full text from an OCR tool result (joined 'text' or lines)."""
    if not data:
        return ""
    if data.get("text"):
        return str(data["text"])
    return " ".join((r.get("text", "") for r in (data.get("results") or []))).strip()


class OcrDigestSkill(Skill):
    name = "ocr_digest"
    description = (
        "Run OCR on an image, summarize the extracted text, and optionally "
        "translate the summary. Orchestrates the 'ocr', 'summarize' and "
        "(optionally) 'translate' tools."
    )
    parameters = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "Absolute path to the image to OCR."},
            "engine": {
                "type": "string",
                "enum": ["paddle", "vietocr", "paddleocr_modern", "glmocr"],
                "description": "OCR engine (optional).",
            },
            "to_lang": {
                "type": "string",
                "description": "If set, also translate the summary into this language.",
            },
        },
        "required": ["image_path"],
    }

    def run(self, ctx: SkillContext, *, image_path: str, engine: Optional[str] = None,
            to_lang: Optional[str] = None, **_: Any) -> SkillResult:
        o = ctx.tools.run("ocr", image_path=image_path, engine=engine)
        steps = [{"tool": "ocr", "ok": o.ok, "meta": o.meta}]
        if not o.ok:
            return SkillResult.failure(f"ocr failed: {o.error}", steps=steps)

        text = _ocr_text(o.data)
        if not text:
            return SkillResult.failure("OCR produced no text", data={"text": ""}, steps=steps)

        s = ctx.tools.run("summarize", text=text)
        steps.append({"tool": "summarize", "ok": s.ok, "meta": s.meta})
        if not s.ok:
            return SkillResult.failure(f"summarize failed: {s.error}", data={"text": text}, steps=steps)

        summary = s.data.get("summary", "")
        data = {"text": text, "summary": summary}

        if to_lang:
            t = ctx.tools.run("translate", text=summary, to_lang=to_lang)
            steps.append({"tool": "translate", "ok": t.ok, "meta": t.meta})
            if t.ok:
                data["translated_summary"] = t.data.get("translated", "")
                data["to_lang"] = to_lang

        return SkillResult.success(data, steps=steps)
