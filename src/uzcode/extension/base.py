"""Extension hook registry (no Protocol — callables only)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from uzcode.skills.registry import SkillRegistry
from uzcode.tools.registry import ToolHandler, ToolRegistry

HookFn = Callable[[dict[str, Any]], dict[str, Any]]
ActionFn = Callable[[dict[str, Any]], dict[str, Any]]

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


@dataclass(frozen=True)
class _ActionRegistration:
    name: str
    fn: ActionFn
    order: int


class HookRegistry:
    """Collects hook callables, tools, skills, and CLI actions registered by extensions."""

    def __init__(
        self,
        order_overrides: dict[str, dict[str, int]] | None = None,
        tools: ToolRegistry | None = None,
        skills: SkillRegistry | None = None,
    ) -> None:
        self._order_overrides = order_overrides or {}
        self._hooks: dict[str, list[_Registration]] = {h: [] for h in HOOKS}
        self._actions: dict[str, _ActionRegistration] = {}
        self.tools = tools if tools is not None else ToolRegistry()
        self.skills = skills if skills is not None else SkillRegistry()

    def on(self, hook: str, fn: HookFn, *, order: int, name: str) -> None:
        if hook not in self._hooks:
            known = ", ".join(HOOKS)
            raise ValueError(f"Unknown hook {hook!r}; expected one of: {known}")
        if any(r.name == name for r in self._hooks[hook]):
            raise ValueError(f"Duplicate registration for hook {hook!r} name {name!r}")
        self._hooks[hook].append(_Registration(name=name, fn=fn, order=order))

    def action(self, name: str, fn: ActionFn, *, order: int = 0) -> None:
        """Register a CLI/API action (e.g. file-changed). Name must be unique."""
        key = str(name).strip()
        if not key:
            raise ValueError("Action name must not be empty")
        if key in self._actions:
            raise ValueError(f"Duplicate registration for action {key!r}")
        self._actions[key] = _ActionRegistration(name=key, fn=fn, order=order)

    def actions(self) -> list[str]:
        """Registered action names sorted by order then name."""
        return [
            r.name
            for r in sorted(
                self._actions.values(),
                key=lambda r: (r.order, r.name),
            )
        ]

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

    def run_action(self, name: str, ctx: dict[str, Any]) -> dict[str, Any]:
        """Run one registered action by name."""
        key = str(name).strip()
        reg = self._actions.get(key)
        if reg is None:
            known = ", ".join(self.actions()) or "(none)"
            raise ValueError(f"Unknown action {key!r}; registered: {known}")
        ctx = dict(ctx)
        ctx["action"] = key
        return reg.fn(ctx)

    def run_actions(
        self, names: list[str], ctx: dict[str, Any]
    ) -> dict[str, Any]:
        """Run named actions in the given order (each must be registered)."""
        for name in names:
            ctx = self.run_action(name, ctx)
        return ctx
