"""Built-in web extension — web_search / web_fetch tools + mentions."""

from __future__ import annotations

from typing import Any

from uzcode.tools.registry import tool_cfg

from . import handlers
from .mentions import handle_web_mentions

_SEARCH_PARAMS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query string",
        },
        "max_results": {
            "type": "integer",
            "description": "Optional max number of results (default from cfg or 5)",
        },
    },
    "required": ["query"],
}

_FETCH_PARAMS = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "HTTP(S) URL to fetch and extract readable text from",
        },
        "timeout_sec": {
            "type": "number",
            "description": "Optional request timeout in seconds (default from cfg or 30)",
        },
    },
    "required": ["url"],
}


def register(registry, config) -> None:
    max_results, backend = handlers.search_defaults(tool_cfg(config, "web_search"))
    max_chars, timeout_sec = handlers.fetch_defaults(tool_cfg(config, "web_fetch"))

    registry.tool(
        "web_search",
        description=(
            "Search the web by keyword; returns titles, URLs, and short snippets"
        ),
        parameters=_SEARCH_PARAMS,
        handler=handlers.make_web_search(
            default_max_results=max_results, default_backend=backend
        ),
    )
    registry.tool(
        "web_fetch",
        description=(
            "Fetch a single HTTP(S) URL and extract readable page text (markdown)"
        ),
        parameters=_FETCH_PARAMS,
        handler=handlers.make_web_fetch(
            default_max_chars=max_chars, default_timeout_sec=timeout_sec
        ),
    )

    def handle_request(ctx: dict[str, Any]) -> dict[str, Any]:
        return handle_web_mentions(ctx, registry)

    registry.on("handle_request", handle_request, order=30, name="web")
