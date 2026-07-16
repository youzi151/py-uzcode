"""Middleware hook registry (no Protocol — callables only)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

HookFn = Callable[[dict[str, Any]], dict[str, Any]]

HOOKS = (
    "before_llm",
    "after_llm",
    "before_tool",
    "after_tool",
    "on_result",
    "on_error",
)


@dataclass(frozen=True)
class _Registration:
    name: str
    fn: HookFn
    order: int


class HookRegistry:
    """Collects hook callables; runs them sorted by effective order per hook."""

    def __init__(
        self,
        order_overrides: dict[str, dict[str, int]] | None = None,
    ) -> None:
        self._order_overrides = order_overrides or {}
        self._hooks: dict[str, list[_Registration]] = {h: [] for h in HOOKS}

    def on(self, hook: str, fn: HookFn, *, order: int, name: str) -> None:
        if hook not in self._hooks:
            known = ", ".join(HOOKS)
            raise ValueError(f"Unknown hook {hook!r}; expected one of: {known}")
        if any(r.name == name for r in self._hooks[hook]):
            raise ValueError(f"Duplicate registration for hook {hook!r} name {name!r}")
        self._hooks[hook].append(_Registration(name=name, fn=fn, order=order))

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
