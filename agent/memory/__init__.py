"""Memory layer — durable agent session history (Phase 6, additive).

    User → Agent Core → Skills → Tools → Knowledge → Memory → Response

The Memory layer lets the Agent Core be given prior turns of a session without
knowing where they are stored. The DB-backed ``ConversationMemory`` uses its own
``agent_conversations`` / ``agent_messages`` tables, so existing chat history is
untouched and memory stays isolated from chat business logic.

This package imports no models at import time (``models`` is imported lazily
inside ``ConversationMemory``), preserving the model-free ``import agent``.
"""

from .base import AgentMemory, InMemoryAgentMemory, Message
from .conversation_memory import ConversationMemory

__all__ = [
    "AgentMemory",
    "InMemoryAgentMemory",
    "ConversationMemory",
    "Message",
]
