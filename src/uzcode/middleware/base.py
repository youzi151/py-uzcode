"""Middleware hook registry (no Protocol — callables only)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from uzcode.skills.registry import SkillRegistry
from uzcode.tools.registry import ToolHandler, ToolRegistry

HookFn = Callable[[dict[str, Any]], dict[str, Any]]

HOOKS = (
    "handle_request",
    "before_llm",
    "after_llm",
    "before_tool",
    "after_tool",
    "after_tools",
    "on_result",
    "on_error",
)


@dataclass(frozen=True)
class _Registration:
    name: str
    fn: HookFn
    order: int


class HookRegistry:
    """Collects hook callables and tools registered by middleware."""

    def __init__(
        self,
        order_overrides: dict[str, dict[str, int]] | None = None,
        tools: ToolRegistry | None = None,
        skills: SkillRegistry | None = None,
    ) -> None:
        self._order_overrides = order_overrides or {}
        self._hooks: dict[str, list[_Registration]] = {h: [] for h in HOOKS}
        self.tools = tools if tools is not None else ToolRegistry()
        self.skills = skills if skills is not None else SkillRegistry()

    def on(self, hook: str, fn: HookFn, *, order: int, name: str) -> None:
        if hook not in self._hooks:
            known = ", ".join(HOOKS)
            raise ValueError(f"Unknown hook {hook!r}; expected one of: {known}")
        if any(r.name == name for r in self._hooks[hook]):
            raise ValueError(f"Duplicate registration for hook {hook!r} name {name!r}")
        self._hooks[hook].append(_Registration(name=name, fn=fn, order=order))

    def tool(
        self,
        name: str,
        *,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
    ) -> None:
        self.tools.register(
            name,
            description=description,
            parameters=parameters,
            handler=handler,
        )

    def skill(
        self,
        name: str,
        *,
        description: str = "",
        body: str,
        root_relpath: str | None = None,
        source: str = "code:register",
    ) -> None:
        """Register a runtime (code) skill; does not write to the skills directory."""
        self.skills.register(
            name,
            description=description,
            body=body,
            root_relpath=root_relpath,
            source=source,
        )

    def _effective_order(self, hook: str, name: str, default: int) -> int:
        override = self._order_overrides.get(hook, {}).get(name)
        return default if override is None else int(override)

    def run(self, hook: str, ctx: dict[str, Any]) -> dict[str, Any]:
        if hook not in self._hooks:
            known = ", ".join(HOOKS)
            raise ValueError(f"Unknown hook {hook!r}; expected one of: {known}")
        regs = sorted(
            self._hooks[hook],
            key=lambda r: (self._effective_order(hook, r.name, r.order), r.name),
        )
        for reg in regs:
            ctx = reg.fn(ctx)
        return ctx
