"""Knowledge Search Tool — wraps the Knowledge layer (DocumentKnowledge).

Returns ranked snippets + their source file_id and score; it does NOT generate an
answer (that's the chat tool / a skill). Like the chat tool, ``allowed_file_ids``
is injected by the platform/Agent Core and is deliberately absent from the public
schema — the LLM must never choose the tenancy scope.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import Tool, ToolResult


class KnowledgeSearchTool(Tool):
    name = "knowledge_search"
    description = (
        "Search the user's indexed documents and return the most relevant text "
        "snippets with their source file_id and similarity score. Use this to "
        "gather supporting evidence; it returns snippets, not a written answer."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "top_k": {"type": "integer", "description": "How many snippets to return.", "default": 5},
            "file_id": {
                "type": "string",
                "description": "Restrict the search to a single document (optional).",
            },
        },
        "required": ["query"],
    }

    def run(self, query: str, top_k: int = 5, file_id: Optional[str] = None,
            allowed_file_ids: Optional[set] = None, **_: Any) -> ToolResult:
        from agent.knowledge import get_knowledge_registry

        # Tenancy guard (defense-in-depth): drop a file_id the caller does NOT own —
        # retrieval bypasses the allowed-id filter when a specific file_id is given,
        # so an unowned id would leak another user's document. None scope (admin)
        # keeps no restriction. Mirrors the chat tool / research skill guard.
        if file_id and allowed_file_ids is not None and file_id not in allowed_file_ids:
            file_id = None

        # Retrieve through the composite over all registered KnowledgeSources, so
        # the tool widens automatically when more sources are added.
        result = get_knowledge_registry().composite().retrieve(
            query, top_k=top_k, allowed_file_ids=allowed_file_ids, file_id=file_id
        )
        return ToolResult.success(result.to_dict(), citations=len(result.citations))
