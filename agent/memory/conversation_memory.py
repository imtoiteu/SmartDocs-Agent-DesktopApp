"""ConversationMemory — durable, DB-backed agent session memory (Phase 6).

Persists to its OWN tables (``agent_conversations`` / ``agent_messages``) via the
helpers in ``models``, so the existing chat history (``chat_conversations``) is
never touched and memory stays isolated from chat business logic.

``models`` is imported lazily inside each method so that ``import agent`` stays
free of the database / Flask stack (a tested invariant). All calls must run
inside a Flask app context (the routes that use this already do).
"""

from __future__ import annotations

from typing import List, Optional

from .base import AgentMemory, Message


class ConversationMemory(AgentMemory):
    name = "agent-db"

    def load_history(self, conversation_id, *,
                     limit: Optional[int] = None) -> List[Message]:
        if conversation_id is None:
            return []
        from models import AgentMessage  # lazy: keep `import agent` model-free
        q = (AgentMessage.query
             .filter_by(conversation_id=conversation_id)
             .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc()))
        if limit is not None:
            q = q.limit(max(limit, 0))
        # Newest-first from the DB (so LIMIT keeps the newest turns), then
        # reversed back to chronological order for the LLM.
        rows = list(reversed(q.all()))
        return [{"role": m.role, "content": m.content} for m in rows]

    def append_turn(self, conversation_id, role: str, content: str, *,
                    tool_calls: Optional[List[str]] = None,
                    provider: Optional[str] = None):
        """Persist one turn; returns the new message id (or None). The id lets
        callers attach per-turn artifact references (Phase 16)."""
        if conversation_id is None:
            return None
        from models import add_agent_message  # lazy: keep `import agent` model-free
        # Auto-title the session from its first user turn (mirrors chat titling).
        return add_agent_message(conversation_id, role, content,
                                 tool_calls=tool_calls, provider=provider,
                                 set_title_if_empty=(role == "user"))
