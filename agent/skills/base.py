"""Skills layer — reusable, lightweight workflows that orchestrate tools/knowledge.

Skills orchestrate; Tools execute (SmartDocs-Agent/CLAUDE.md → Skills). A skill
may call several tools and/or a knowledge source, validate, and synthesize a
structured result. Skills hold NO business logic — they compose capabilities.

A ``SkillContext`` carries the dependencies a skill may use (the tool registry,
the tenant scope, an optional knowledge source and LLM provider) so skills stay
stateless and independently testable with stubs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..tools import ToolRegistry


@dataclass
class SkillContext:
    tools: ToolRegistry
    allowed_file_ids: Optional[set] = None
    knowledge: Optional[Any] = None          # agent.knowledge.KnowledgeSource
    provider: Optional[Any] = None           # agent.core.LLMProvider


@dataclass
class SkillResult:
    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)
    steps: List[Dict[str, Any]] = field(default_factory=list)  # provenance
    error: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "data": self.data, "steps": self.steps,
                "error": self.error, "meta": self.meta}

    @classmethod
    def success(cls, data: Optional[Dict[str, Any]] = None, *, steps=None, **meta: Any) -> "SkillResult":
        return cls(ok=True, data=dict(data or {}), steps=list(steps or []),
                   meta={k: v for k, v in meta.items() if v is not None})

    @classmethod
    def failure(cls, error: Any, *, data=None, steps=None, **meta: Any) -> "SkillResult":
        return cls(ok=False, data=dict(data or {}), steps=list(steps or []),
                   error=str(error), meta={k: v for k, v in meta.items() if v is not None})


class Skill(ABC):
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {"type": "object", "properties": {}}

    @abstractmethod
    def run(self, ctx: SkillContext, **kwargs: Any) -> SkillResult:
        raise NotImplementedError

    def spec(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: Dict[str, Skill] = {}

    def register(self, skill: Skill) -> Skill:
        if not getattr(skill, "name", ""):
            raise ValueError("Skill must define a non-empty .name")
        if skill.name in self._skills:
            raise ValueError(f"Skill {skill.name!r} is already registered")
        self._skills[skill.name] = skill
        return skill

    def has(self, name: str) -> bool:
        return name in self._skills

    def get(self, name: str) -> Skill:
        if name not in self._skills:
            raise KeyError(f"Unknown skill: {name!r}. Available: {self.names()}")
        return self._skills[name]

    def names(self) -> List[str]:
        return sorted(self._skills)

    def list(self) -> List[Skill]:
        return [self._skills[n] for n in self.names()]

    def specs(self) -> List[Dict[str, Any]]:
        return [s.spec() for s in self.list()]

    def run(self, name: str, ctx: SkillContext, **kwargs: Any) -> SkillResult:
        try:
            skill = self.get(name)
        except KeyError as exc:
            return SkillResult.failure(str(exc), skill=name)
        try:
            result = skill.run(ctx, **kwargs)
            if not isinstance(result, SkillResult):
                result = SkillResult.success(result if isinstance(result, dict) else {"value": result})
        except Exception as exc:  # noqa: BLE001 — uniform skill-level error capture
            result = SkillResult.failure(f"{type(exc).__name__}: {exc}")
        result.meta.setdefault("skill", name)
        return result
