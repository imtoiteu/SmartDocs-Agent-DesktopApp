"""Memory layer — durable agent conversation history (Phase 6).

Memory is isolated from business logic (SmartDocs-Agent/CLAUDE.md → Memory
Layer). An ``AgentMemory`` loads prior turns as plain chat messages and appends
new turns, so the Agent Core can be given multi-turn context without knowing
where (or whether) the history is stored.

Implementations:
* ``ConversationMemory``   — durable, DB-backed (its own ``agent_*`` tables, so
                             chat history is never touched). See
                             ``conversation_memory.py``.
* ``InMemoryAgentMemory``  — process-local dict, for tests and ephemeral use.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

Message = Dict[str, str]  # {"role": "...", "content": "..."} — matches core.provider.Message


class AgentMemory(ABC):
    """Loads/saves agent session turns. Storage detail is hidden from the caller."""

    name: str = "memory"

    @abstractmethod
    def load_history(self, conversation_id, *,
                     limit: Optional[int] = None) -> List[Message]:
        """Return prior turns as ``[{role, content}, ...]`` in chronological order.

        An unknown / ``None`` ``conversation_id`` yields an empty list.
        ``limit`` keeps only the NEWEST ``limit`` turns (None = all) — callers
        bound the context they feed an LLM instead of replaying a whole session.
        """
        raise NotImplementedError

    @abstractmethod
    def append_turn(self, conversation_id, role: str, content: str, *,
                    tool_calls: Optional[List[str]] = None,
                    provider: Optional[str] = None) -> None:
        """Persist one turn. A ``None`` ``conversation_id`` is a no-op."""
        raise NotImplementedError


class InMemoryAgentMemory(AgentMemory):
    """Process-local memory keyed by conversation id (tests / ephemeral use)."""

    name = "in-memory"

    def __init__(self) -> None:
        self._turns: Dict[object, List[dict]] = {}

    def load_history(self, conversation_id, *,
                     limit: Optional[int] = None) -> List[Message]:
        if conversation_id is None:
            return []
        turns = self._turns.get(conversation_id, [])
        if limit is not None:
            turns = turns[-limit:] if limit > 0 else []
        return [{"role": t["role"], "content": t["content"]} for t in turns]

    def append_turn(self, conversation_id, role: str, content: str, *,
                    tool_calls: Optional[List[str]] = None,
                    provider: Optional[str] = None) -> None:
        if conversation_id is None:
            return
        self._turns.setdefault(conversation_id, []).append(
            {"role": role, "content": content,
             "tool_calls": list(tool_calls or []), "provider": provider})
