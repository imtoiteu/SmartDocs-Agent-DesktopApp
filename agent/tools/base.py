"""Tool abstraction — the uniform contract every SmartDocs tool implements.

A ``Tool`` is a thin wrapper around an existing SmartDocs *service*. It declares:

* ``name``        — unique, machine-friendly identifier
* ``description`` — natural-language summary (consumed by the Agent Core / LLM)
* ``parameters``  — JSON Schema (``type: object``) describing ``run()`` kwargs.
                    This is what makes a tool callable by an LLM via
                    function-calling in Phase 3 (provider-neutral shape).

Design rules (see SmartDocs-Agent/CLAUDE.md → Tools):
* one responsibility per tool;
* return a structured ``ToolResult``;
* NO orchestration and NO business logic inside a tool — that lives in the
  underlying service (which the tool reuses) and, later, the Skills / Agent Core.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ToolResult:
    """Uniform, JSON-serialisable result returned by every tool.

    ``data`` carries the underlying service payload unchanged (so existing
    contracts are preserved); ``meta`` carries small, normalised annotations
    (engine used, timing, tool name); ``error`` is set only when ``ok`` is False.
    """

    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "data": self.data, "error": self.error, "meta": self.meta}

    @classmethod
    def success(cls, data: Optional[Dict[str, Any]] = None, **meta: Any) -> "ToolResult":
        return cls(ok=True, data=dict(data or {}), meta={k: v for k, v in meta.items() if v is not None})

    @classmethod
    def failure(cls, error: Any, **meta: Any) -> "ToolResult":
        return cls(ok=False, error=str(error), meta={k: v for k, v in meta.items() if v is not None})


class Tool(ABC):
    """Base class for all tools."""

    name: str = ""
    description: str = ""
    # JSON Schema for run() kwargs. Default: no parameters.
    parameters: Dict[str, Any] = {"type": "object", "properties": {}}

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool. Implementations should return a ``ToolResult``.

        Implementations may raise; the registry's ``run()`` captures exceptions
        and converts them into ``ToolResult.failure`` so callers get a uniform
        shape and never crash on a tool error.
        """
        raise NotImplementedError

    def __call__(self, **kwargs: Any) -> ToolResult:
        return self.run(**kwargs)

    def spec(self) -> Dict[str, Any]:
        """Provider-neutral function spec (OpenAI / Anthropic-compatible shape).

        Phase 3's Agent Core turns this into whatever a given LLM provider wants
        (e.g. ``{"type": "function", "function": spec}`` for OpenAI, or
        ``{"name", "description", "input_schema"}`` for Anthropic).
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
