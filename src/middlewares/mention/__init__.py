"""Built-in mention middleware — expand @ / # mentions on handle_request."""

from __future__ import annotations

from typing import Any

from .expand import expand_mentions


def register(registry, config) -> None:
    def handle_request(ctx: dict[str, Any]) -> dict[str, Any]:
        return expand_mentions(ctx, registry)

    registry.on("handle_request", handle_request, order=10, name="mention")
