"""Skills layer — reusable workflows that orchestrate tools and knowledge.

Public API:
    Skill, SkillResult, SkillContext, SkillRegistry
    build_default_skill_registry()  — registry with the built-in skills
    get_skill_registry()            — process-wide default (lazy)
    default_context(...)            — a SkillContext wired with the default
                                      tool registry, knowledge source and provider
"""

from __future__ import annotations

from typing import Optional

from .base import Skill, SkillContext, SkillResult, SkillRegistry

_DEFAULT_SKILL_REGISTRY: Optional[SkillRegistry] = None


def build_default_skill_registry() -> SkillRegistry:
    from .summarize_translate import SummarizeTranslateSkill
    from .ocr_digest import OcrDigestSkill
    from .research import ResearchSkill
    from .summarize import SummarizeSkill
    from .translate import TranslateSkill
    from .correct import CorrectSkill
    from .docqa import DocQaSkill

    reg = SkillRegistry()
    reg.register(SummarizeTranslateSkill())
    reg.register(OcrDigestSkill())
    reg.register(ResearchSkill())
    # Atomic single-capability actions (thin wrappers over the underlying tools).
    # Run-Action-only — the agent loop uses the tools directly, so these are
    # intentionally absent from the agent's safe skill registry. docqa is the
    # single chat-based Document QA action ("Ask My Documents"); it supersedes
    # research, which stays registered for rollback but is unexposed.
    reg.register(SummarizeSkill())
    reg.register(TranslateSkill())
    reg.register(CorrectSkill())
    reg.register(DocQaSkill())
    return reg


def get_skill_registry() -> SkillRegistry:
    global _DEFAULT_SKILL_REGISTRY
    if _DEFAULT_SKILL_REGISTRY is None:
        _DEFAULT_SKILL_REGISTRY = build_default_skill_registry()
    return _DEFAULT_SKILL_REGISTRY


def default_context(allowed_file_ids: Optional[set] = None) -> SkillContext:
    """Build a SkillContext wired with the default tool registry, the document
    knowledge source, and the default (offline-first) LLM provider."""
    from ..tools import get_registry
    from ..knowledge import get_knowledge_registry
    from ..core.llm_gateway import provider_for_task

    return SkillContext(
        tools=get_registry(),
        allowed_file_ids=allowed_file_ids,
        knowledge=get_knowledge_registry().composite(),
        provider=provider_for_task("agent"),
    )


__all__ = [
    "Skill",
    "SkillResult",
    "SkillContext",
    "SkillRegistry",
    "build_default_skill_registry",
    "get_skill_registry",
    "default_context",
]
