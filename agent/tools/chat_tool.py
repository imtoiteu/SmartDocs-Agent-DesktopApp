"""Chat Tool — wraps ``services.chat_service.chat`` (RAG over user documents).

Security note: ``allowed_file_ids`` scopes 'doc_all' retrieval to the caller's
own documents. It is deliberately NOT part of the public ``parameters`` schema —
an LLM/agent must never choose it. The platform layer (route / Agent Core)
injects it from the authenticated user, exactly as the existing ``chat_bp`` does.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .base import Tool, ToolResult


class ChatTool(Tool):
    name = "chat"
    description = (
        "Answer a question with the SmartDocs chat service. 'doc_current' uses "
        "RAG over one document (file_id), 'doc_all' over all the user's "
        "documents, and 'general' is plain chat with no retrieval. Returns the "
        "answer plus cited sources."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The user's question."},
            "file_id": {
                "type": "string",
                "description": "Document file_id to ground the answer on (for mode 'doc_current').",
            },
            "mode": {
                "type": "string",
                "description": "Retrieval scope.",
                "enum": ["doc_current", "doc_all", "general"],
                "default": "doc_current",
            },
            "history": {
                "type": "array",
                "description": "Prior conversation turns as [{role, content}, ...].",
                "items": {"type": "object"},
            },
        },
        "required": ["query"],
    }

    def run(self, query: str, file_id: Optional[str] = None,
            mode: str = "doc_current", history: Optional[List[dict]] = None,
            allowed_file_ids: Optional[set] = None, **_: Any) -> ToolResult:
        from services import chat_service

        # Tenancy guard (defense-in-depth): the LLM chooses file_id, but RAG
        # retrieval bypasses the allowed-id filter when a specific file_id is given
        # (chat_service.retrieve_chunks), so a file_id the caller does NOT own must
        # be dropped here — never grounded on. It safely degrades to a scoped
        # all-documents search. None scope (admin) keeps no restriction. This mirrors
        # the guard in the research skill.
        if file_id and allowed_file_ids is not None and file_id not in allowed_file_ids:
            file_id = None

        res = chat_service.chat(
            query,
            file_id=file_id,
            mode=mode,
            history=history,
            allowed_file_ids=allowed_file_ids,
        )
        return ToolResult.success(
            res,
            engine=res.get("engine_used"),
            chunks_found=res.get("chunks_found"),
            chat_elapsed_s=res.get("elapsed_s"),
        )
