"""Tool Registry — register, look up, introspect, and invoke tools uniformly.

The registry is the single place the Agent Core (Phase 3) will go to discover
available capabilities (``specs()`` → LLM function-calling manifest) and to
dispatch a chosen tool (``run()``). Invocation is wrapped so that:

* an unknown tool name returns a ``ToolResult.failure`` (never raises);
* any exception inside a tool is captured as ``ToolResult.failure``;
* every result is annotated with the tool name and elapsed time.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    # ── registration ──────────────────────────────────────────────────────────
    def register(self, tool: Tool) -> Tool:
        name = getattr(tool, "name", "")
        if not name:
            raise ValueError("Tool must define a non-empty .name")
        if name in self._tools:
            raise ValueError(f"Tool {name!r} is already registered")
        self._tools[name] = tool
        return tool

    # ── lookup / introspection ─────────────────────────────────────────────────
    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name!r}. Available: {self.names()}")
        return self._tools[name]

    def names(self) -> List[str]:
        return sorted(self._tools)

    def list(self) -> List[Tool]:
        return [self._tools[n] for n in self.names()]

    def specs(self) -> List[Dict[str, Any]]:
        """Function-calling manifest for all registered tools."""
        return [t.spec() for t in self.list()]

    # ── invocation ──────────────────────────────────────────────────────────────
    def run(self, name: str, **kwargs: Any) -> ToolResult:
        try:
            tool = self.get(name)
        except KeyError as exc:
            return ToolResult.failure(str(exc), tool=name)

        t0 = time.time()
        try:
            result = tool.run(**kwargs)
            if not isinstance(result, ToolResult):
                # Be forgiving if a tool returns a bare dict/value.
                payload = result if isinstance(result, dict) else {"value": result}
                result = ToolResult.success(payload)
        except Exception as exc:  # noqa: BLE001 — uniform tool-level error capture
            result = ToolResult.failure(f"{type(exc).__name__}: {exc}")

        result.meta.setdefault("tool", name)
        result.meta.setdefault("elapsed_ms", round((time.time() - t0) * 1000, 1))
        return result


# ── default registry (lazy singleton) ──────────────────────────────────────────
_DEFAULT_REGISTRY: Optional[ToolRegistry] = None


def build_default_registry() -> ToolRegistry:
    """Build a fresh registry with all built-in SmartDocs tools registered.

    Tool modules are imported lazily here so that importing ``agent.tools`` (and
    thus building the registry) does NOT import the heavy service stack
    (torch/paddle/transformers). Those are imported only when a tool actually
    runs.
    """
    from .ocr_tool import OcrTool
    from .translate_tool import TranslateTool
    from .summarize_tool import SummarizeTool
    from .chat_tool import ChatTool
    from .knowledge_tool import KnowledgeSearchTool
    from .correction_tool import CorrectionTool

    reg = ToolRegistry()
    reg.register(OcrTool())
    reg.register(TranslateTool())
    reg.register(SummarizeTool())
    reg.register(ChatTool())
    reg.register(KnowledgeSearchTool())
    reg.register(CorrectionTool())
    return reg


def get_registry() -> ToolRegistry:
    """Return the process-wide default registry, building it once on first use."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_registry()
    return _DEFAULT_REGISTRY
