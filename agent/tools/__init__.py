"""Tools layer — uniform wrappers over existing SmartDocs services.

Public API:
    Tool, ToolResult            — the tool contract
    ToolRegistry                — registry type
    get_registry()              — process-wide default registry (lazy)
    build_default_registry()    — fresh registry with the built-in tools
"""

from .base import Tool, ToolResult
from .registry import ToolRegistry, get_registry, build_default_registry

__all__ = [
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "get_registry",
    "build_default_registry",
]
