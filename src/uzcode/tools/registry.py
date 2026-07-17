"""Thin tool registry — mids register handlers; core only looks up / executes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from uzcode.data import Config

ToolHandler = Callable[[dict[str, Any], dict[str, Any]], str]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


def tool_cfg(config: Config, name: str) -> dict[str, Any]:
    raw = config.tools.get(name)
    return raw if isinstance(raw, dict) else {}


def tool_enabled(config: Config, name: str) -> bool:
    """Per-tool enable; default True when section/key omitted."""
    cfg = tool_cfg(config, name)
    if "enable" not in cfg:
        return True
    return bool(cfg["enable"])


def tool_permission(config: Config, name: str) -> str:
    """Per-tool permission: ask | approve | custom.

    Default when omitted from cfg: ask (never name-based).
    """
    cfg = tool_cfg(config, name)
    raw = cfg.get("permission")
    if raw is None:
        return "ask"
    value = str(raw).strip().lower()
    if value in ("ask", "approve", "custom"):
        return value
    raise ValueError(
        f"tools.{name}.permission must be 'ask', 'approve', or 'custom', "
        f"got {raw!r}"
    )


class ToolRegistry:
    """Register tools offered by middleware; filter by cfg for the LLM."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        *,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
    ) -> None:
        if name in self._tools:
            raise ValueError(f"Duplicate tool registration: {name!r}")
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def openai_tools(self, config: Config) -> list[dict[str, Any]]:
        """OpenAI Chat Completions tools list, filtered by tools.*.enable."""
        out: list[dict[str, Any]] = []
        for name in self.names():
            if not tool_enabled(config, name):
                continue
            spec = self._tools[name]
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.parameters,
                    },
                }
            )
        return out

    def execute(self, name: str, arguments: dict[str, Any], ctx: dict[str, Any]) -> str:
        spec = self._tools.get(name)
        if spec is None:
            return f"Error: unknown tool {name!r}"
        return spec.handler(arguments, ctx)
