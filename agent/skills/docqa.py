"""DocQaSkill — answer a question grounded in the user's documents (chat-based).

The single user-facing Document QA action ("Ask My Documents"). A thin wrapper
over the 'chat' tool (RAG + LLM answer), so QA uses the SAME synthesis as the
platform's Chat experience — not a second chat system. Single-shot by design: no
conversation history is threaded here (multi-turn lives in the Chat feature).

Scope: an optional owned ``file_id`` → answer over that one document
('doc_current'); otherwise over the whole owned library ('doc_all'). Tenancy is
enforced HERE and in the chat tool (the LLM never widens its own scope).
"""

from __future__ import annotations

from typing import Any, List, Optional

from .base import Skill, SkillContext, SkillResult


class DocQaSkill(Skill):
    name = "docqa"
    description = (
        "Answer a question grounded in the user's documents: retrieve the most "
        "relevant passages and write an answer with cited sources. Optionally "
        "scope to a single document."
    )
    # file_id is intentionally NOT advertised: the HTTP UI supplies the scope; a
    # caller (or LLM) must never choose an arbitrary document id.
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The question to answer."},
        },
        "required": ["query"],
    }

    def run(self, ctx: SkillContext, *, query: str,
            file_id: Optional[str] = None, **_: Any) -> SkillResult:
        # Ownership-validate the optional single-document scope (defense-in-depth;
        # mirrors the chat tool / research guards). An unowned id is ignored → the
        # answer falls back to the whole owned library rather than leaking.
        if file_id and ctx.allowed_file_ids is not None and file_id not in ctx.allowed_file_ids:
            file_id = None
        mode = "doc_current" if file_id else "doc_all"

        # Single-shot: no history is passed. allowed_file_ids scopes retrieval to
        # the caller's documents (the LLM never chooses it).
        r = ctx.tools.run("chat", query=query, file_id=file_id, mode=mode,
                          allowed_file_ids=ctx.allowed_file_ids)
        steps = [{"tool": "chat", "ok": r.ok, "meta": r.meta}]
        if not r.ok:
            return SkillResult.failure(f"chat failed: {r.error}", steps=steps)

        data = r.data or {}
        # chat_service sources are already {file_id, score, excerpt} — the citation
        # shape the results layer + UI render. Keep only entries with a file_id.
        citations: List[dict] = [s for s in (data.get("sources") or [])
                                 if isinstance(s, dict) and s.get("file_id")]
        return SkillResult.success(
            {"answer": data.get("answer", ""), "citations": citations}, steps=steps)
