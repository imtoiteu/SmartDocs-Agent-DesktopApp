"""ResearchSkill — retrieve from Knowledge, then digest into a brief + citations.

Demonstrates the Skills ↔ Knowledge ↔ Tools interplay: it retrieves ranked
snippets from the Knowledge layer (which reuses the existing RAG) and condenses
them with the 'summarize' tool, returning the supporting citations. This is a
retrieval+digest helper — full conversational QA remains the 'chat' tool.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import Skill, SkillContext, SkillResult


class ResearchSkill(Skill):
    name = "research"
    description = (
        "Answer a question grounded in the user's indexed documents: retrieve "
        "the most relevant snippets, condense them into a short brief, and return "
        "the supporting citations."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The question to research."},
            "top_k": {"type": "integer", "description": "How many snippets to retrieve.", "default": 5},
        },
        "required": ["query"],
    }

    def run(self, ctx: SkillContext, *, query: str, top_k: int = 5,
            file_id: Optional[str] = None, **_: Any) -> SkillResult:
        if ctx.knowledge is None:
            return SkillResult.failure("no knowledge source configured")

        # Optional single-document scope. Enforce tenancy HERE (defense-in-depth):
        # a file_id the caller doesn't own is ignored — never searched. This guard
        # is required because the underlying retrieval bypasses the allowed-id
        # filter when a specific file_id is supplied.
        if file_id and ctx.allowed_file_ids is not None and file_id not in ctx.allowed_file_ids:
            file_id = None

        kr = ctx.knowledge.retrieve(query, top_k=top_k,
                                    allowed_file_ids=ctx.allowed_file_ids, file_id=file_id)
        steps = [{"knowledge": kr.source, "citations": len(kr.citations)}]
        citations = [c.to_dict() for c in kr.citations]

        if kr.is_empty():
            return SkillResult.success(
                {"answer": "No relevant documents found.", "citations": []}, steps=steps
            )

        s = ctx.tools.run("summarize", text=kr.context_text(), mode="short")
        steps.append({"tool": "summarize", "ok": s.ok, "meta": s.meta})
        if s.ok:
            answer = s.data.get("summary") or kr.context_text()[:500]
        else:
            # Degrade gracefully: return the top snippets if summarization fails.
            answer = kr.context_text()[:500]

        return SkillResult.success({"answer": answer, "citations": citations}, steps=steps)
