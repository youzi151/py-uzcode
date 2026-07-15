"""Middleware hook interface (Phase 3+)."""

from __future__ import annotations

from typing import Any, Protocol


class Middleware(Protocol):
    """Hook interface for middleware plugins."""

    def before_llm(self, ctx: dict[str, Any]) -> dict[str, Any]: ...

    def after_llm(self, ctx: dict[str, Any]) -> dict[str, Any]: ...
