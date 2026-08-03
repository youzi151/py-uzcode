"""Tool registry (handlers come from extensions)."""

from uzcode.tools.registry import (
    ToolHandler,
    ToolRegistry,
    ToolSpec,
    tool_cfg,
    tool_enabled,
    tool_permission,
)

__all__ = [
    "ToolHandler",
    "ToolRegistry",
    "ToolSpec",
    "tool_cfg",
    "tool_enabled",
    "tool_permission",
]
