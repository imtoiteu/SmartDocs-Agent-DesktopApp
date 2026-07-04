"""Agent Core layer — orchestration over Tools and an LLM provider.

Public API:
    LLMProvider, LocalQwenProvider, get_default_provider  — model abstraction
    AgentCore, AgentResult, AgentStep                     — orchestration loop
"""

from .provider import (
    LLMProvider,
    LocalQwenProvider,
    GeminiProvider,
    GroqProvider,
    OpenAICompatibleProvider,
    FallbackProvider,
    Message,
    get_default_provider,
    get_openai_compatible_provider,
    cloud_allowed,
    fit_messages_to_char_budget,
)
from .agent import AgentCore, AgentResult, AgentStep

__all__ = [
    "LLMProvider",
    "LocalQwenProvider",
    "GeminiProvider",
    "GroqProvider",
    "OpenAICompatibleProvider",
    "FallbackProvider",
    "Message",
    "get_default_provider",
    "get_openai_compatible_provider",
    "cloud_allowed",
    "fit_messages_to_char_budget",
    "AgentCore",
    "AgentResult",
    "AgentStep",
]
