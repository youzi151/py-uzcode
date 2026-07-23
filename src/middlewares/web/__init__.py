"""Built-in web middleware — mention handlers for search/fetch (tools Phase 7)."""

from __future__ import annotations

from typing import Any

from .mentions import handle_web_mentions


def register(registry, config) -> None:
    """Register web mention handling. web_search / web_fetch tools come later."""

    def handle_request(ctx: dict[str, Any]) -> dict[str, Any]:
        return handle_web_mentions(ctx, registry)

    registry.on("handle_request", handle_request, order=30, name="web")
