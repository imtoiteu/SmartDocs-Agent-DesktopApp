"""SmartDocs Agent Platform package (additive; introduced in Phase 2).

Target layered architecture:

    User → Agent Core → Skills → Tools → Knowledge → Memory → Response

Phase 2 introduces the **Tools** layer and a **Tool Registry**. Tools are thin,
uniform, independently-testable wrappers around the EXISTING SmartDocs services
(``services/ocr_service.py``, ``translate_service.py``, ``summary_service.py``,
``chat_service.py``, …). They contain no business logic and no orchestration —
they only adapt a service call into a uniform contract.

Nothing in this package modifies existing routes, services, or UI. Later phases
will add ``skills/``, ``knowledge/`` and ``memory/`` alongside ``tools/`` and
``core/``.

Phase 3 adds the **Agent Core** (``core/``): a model-agnostic orchestration loop
over the Tool Registry, driven by a pluggable ``LLMProvider`` (offline-first
local Qwen by default).
"""

from .tools import Tool, ToolResult, ToolRegistry, get_registry, build_default_registry
from .core import (
    AgentCore,
    AgentResult,
    AgentStep,
    LLMProvider,
    LocalQwenProvider,
    GeminiProvider,
    GroqProvider,
    get_default_provider,
)
from .knowledge import (
    Citation,
    KnowledgeResult,
    KnowledgeSource,
    DocumentKnowledge,
    merge_citations,
    CompositeKnowledge,
    KnowledgeRegistry,
    get_knowledge_registry,
)
from .skills import (
    Skill,
    SkillResult,
    SkillContext,
    SkillRegistry,
    build_default_skill_registry,
    get_skill_registry,
    default_context,
)
from .memory import AgentMemory, InMemoryAgentMemory, ConversationMemory
from .results import (
    collect_doc_outputs,
    doc_artifact_destinations,
    citation_destinations,
    source_document_destination,
    chat_destination,
    dedupe_destinations,
)
from .ocr_routing import select_ocr_engine, normalize_engine as normalize_ocr_engine

__all__ = [
    # tools
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "get_registry",
    "build_default_registry",
    # core
    "AgentCore",
    "AgentResult",
    "AgentStep",
    "LLMProvider",
    "LocalQwenProvider",
    "GeminiProvider",
    "GroqProvider",
    "get_default_provider",
    # knowledge
    "Citation",
    "KnowledgeResult",
    "KnowledgeSource",
    "DocumentKnowledge",
    "merge_citations",
    "CompositeKnowledge",
    "KnowledgeRegistry",
    "get_knowledge_registry",
    # skills
    "Skill",
    "SkillResult",
    "SkillContext",
    "SkillRegistry",
    "build_default_skill_registry",
    "get_skill_registry",
    "default_context",
    # memory
    "AgentMemory",
    "InMemoryAgentMemory",
    "ConversationMemory",
    # results (orchestration → existing-module destinations)
    "collect_doc_outputs",
    "doc_artifact_destinations",
    "citation_destinations",
    "source_document_destination",
    "chat_destination",
    "dedupe_destinations",
    # OCR engine routing (agent picks engine from the request; default GLM)
    "select_ocr_engine",
    "normalize_ocr_engine",
]
