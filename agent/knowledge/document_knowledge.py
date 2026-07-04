"""DocumentKnowledge — retrieval over the user's indexed documents.

Thin wrapper over the EXISTING RAG (``services.chat_service.retrieve_chunks``):
FAISS vector search with TF-IDF fallback, ranking, and per-user scoping via
``allowed_file_ids``. No retrieval logic is duplicated here — this layer only
maps the service's ``(score, chunk, file_id)`` tuples into typed citations.
"""

from __future__ import annotations

from typing import Optional

from .base import Citation, KnowledgeResult, KnowledgeSource


class DocumentKnowledge(KnowledgeSource):
    name = "documents"

    def retrieve(self, query: str, *, top_k: int = 5,
                 allowed_file_ids: Optional[set] = None,
                 file_id: Optional[str] = None) -> KnowledgeResult:
        from services import chat_service  # lazy: keeps the heavy RAG stack out of import time

        rows = chat_service.retrieve_chunks(
            query, file_id=file_id, top_k=top_k, allowed_file_ids=allowed_file_ids
        )
        citations = [
            Citation(file_id=fid, text=chunk, score=round(float(score), 4))
            for (score, chunk, fid) in rows
        ]
        return KnowledgeResult(query=query, citations=citations, source=self.name)
