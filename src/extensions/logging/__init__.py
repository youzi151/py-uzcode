"""Built-in logging extension — logs before/after LLM to stderr."""

from __future__ import annotations

import sys
from typing import Any


def _preview(content: str, limit: int = 120) -> str:
    text = content.replace("\n", "\\n")
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def register(registry, config) -> None:
    def before_llm(ctx: dict[str, Any]) -> dict[str, Any]:
        messages = (ctx.get("state") or {}).get("messages") or []
        last_user = next(
            (m for m in reversed(messages) if m.get("role") == "user"),
            None,
        )
        preview = _preview(last_user.get("content", "")) if last_user else "(none)"
        print(
            f"[logging] before_llm: messages={len(messages)} last_user={preview!r}",
            file=sys.stderr,
        )
        return ctx

    def after_llm(ctx: dict[str, Any]) -> dict[str, Any]:
        messages = (ctx.get("state") or {}).get("messages") or []
        last_asst = next(
            (m for m in reversed(messages) if m.get("role") == "assistant"),
            None,
        )
        preview = _preview(last_asst.get("content", "")) if last_asst else "(none)"
        print(
            f"[logging] after_llm: messages={len(messages)} assistant={preview!r}",
            file=sys.stderr,
        )
        return ctx

    registry.on("before_llm", before_llm, order=100, name="logging")
    registry.on("after_llm", after_llm, order=100, name="logging")
