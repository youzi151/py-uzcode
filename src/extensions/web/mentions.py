"""web mention handlers — @{search|fetch[:!]:...}."""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any

from uzcode.tools.registry import tool_cfg

from . import handlers

_MARK = "web"
_EXPAND_CMDS = frozenset({"search", "fetch"})
_PRECALL_CMDS = frozenset({"search!", "fetch!"})

_CMD_TO_TOOL = {
    "search": "web_search",
    "search!": "web_search",
    "fetch": "web_fetch",
    "fetch!": "web_fetch",
}


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _already_tool_result(
    messages: list[dict[str, Any]], tool_name: str, arg_key: str, arg_val: str
) -> bool:
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") != tool_name:
                continue
            args = _parse_tool_args(fn.get("arguments"))
            if str(args.get(arg_key, "")) != arg_val:
                continue
            tc_id = tc.get("id")
            if any(
                m.get("role") == "tool" and m.get("tool_call_id") == tc_id
                for m in messages
            ):
                return True
    return False


def _synthetic_tool_pair(
    tool_name: str, arguments: dict[str, Any], content: str
) -> list[dict[str, Any]]:
    call_id = f"mention_{uuid.uuid4().hex[:24]}"
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "content": content,
        },
    ]


def _tool_registered(registry: Any, name: str) -> bool:
    tools = getattr(registry, "tools", None)
    if tools is None:
        return False
    get = getattr(tools, "get", None)
    if get is None:
        return False
    return get(name) is not None


def _mark_handled(mention: dict[str, Any]) -> None:
    handled = list(mention.get("handled") or [])
    if _MARK not in handled:
        handled.append(_MARK)
    mention["handled"] = handled


def _search_pair(text: str, config: Any) -> tuple[str, str]:
    """Return (index_replacement, full_tool_content) from one search."""
    max_results, backend = handlers.search_defaults(
        tool_cfg(config, "web_search") if config is not None else {}
    )
    results = handlers.search_results(
        text, max_results=max_results, backend=backend
    )
    return (
        handlers.format_search_index(text, results),
        handlers.format_search_full(text, results),
    )


def _fetch_pair(text: str, config: Any) -> tuple[str, str]:
    """Return (index_replacement, full_tool_content) from one fetch."""
    max_chars, timeout_sec = handlers.fetch_defaults(
        tool_cfg(config, "web_fetch") if config is not None else {}
    )
    page = handlers.fetch_page(text, timeout_sec=timeout_sec)
    url = page.get("url") or text
    title = page.get("title") or ""
    index = handlers.format_fetch_index(url, title)
    if "error" in page and "text" not in page:
        err = page["error"]
        parts = [f"Error: {err}", f"url: {url}"]
        if title:
            parts.append(f"title: {title}")
        return index, "\n".join(parts)
    full = handlers.format_fetch_full(
        url, title, page.get("text") or "", max_chars=max_chars
    )
    return index, full


def handle_web_mentions(ctx: dict[str, Any], registry: Any) -> dict[str, Any]:
    """Handle search/fetch mentions when web_* tools are registered.

    Expand (no bang): title/link index only in ``replacement`` (no body/snippets).
    Precall (bang): same index in ``replacement`` + inject full tool result.
    """
    state = ctx.setdefault("state", {})
    config = ctx.get("config")
    messages = list(state.get("messages") or [])
    mentions = list(state.get("mentions") or [])

    injections: list[tuple[int, list[dict[str, Any]]]] = []
    pending: set[tuple[str, str]] = set()

    for mention in mentions:
        handled = mention.get("handled") or []
        if _MARK in handled:
            continue
        cmd = str(mention.get("cmd") or "")
        if cmd not in _EXPAND_CMDS and cmd not in _PRECALL_CMDS:
            continue

        tool_name = _CMD_TO_TOOL[cmd]
        text = str(mention.get("text") or "")
        if not _tool_registered(registry, tool_name):
            print(
                f"[web] skip mention {mention.get('raw')!r}: "
                f"tool {tool_name!r} not registered",
                file=sys.stderr,
            )
            continue

        base = "search" if cmd.startswith("search") else "fetch"
        arg_key = "query" if base == "search" else "url"
        args = {arg_key: text}
        pend_key = (tool_name, text)
        want_precall = cmd in _PRECALL_CMDS

        try:
            if want_precall:
                if base == "search":
                    index, full = _search_pair(text, config)
                else:
                    index, full = _fetch_pair(text, config)
            elif base == "search":
                max_results, backend = handlers.search_defaults(
                    tool_cfg(config, "web_search") if config is not None else {}
                )
                results = handlers.search_results(
                    text, max_results=max_results, backend=backend
                )
                index, full = handlers.format_search_index(text, results), ""
            else:
                _, timeout_sec = handlers.fetch_defaults(
                    tool_cfg(config, "web_fetch") if config is not None else {}
                )
                page = handlers.fetch_page(text, timeout_sec=timeout_sec)
                index = handlers.format_fetch_index(
                    page.get("url") or text, page.get("title") or ""
                )
                full = ""
        except Exception as exc:  # noqa: BLE001
            print(f"[web] {tool_name} failed: {exc}", file=sys.stderr)
            _mark_handled(mention)
            continue

        mention["replacement"] = index

        if want_precall:
            if pend_key not in pending and not _already_tool_result(
                messages, tool_name, arg_key, text
            ):
                msg_index = int(mention.get("msg_index", -1))
                if msg_index >= 0:
                    injections.append(
                        (msg_index, _synthetic_tool_pair(tool_name, args, full))
                    )
                pending.add(pend_key)

        _mark_handled(mention)

    if injections:
        inject_map: dict[int, list[dict[str, Any]]] = {}
        for idx, pairs in injections:
            inject_map.setdefault(idx, []).extend(pairs)
        for idx in sorted(inject_map.keys(), reverse=True):
            pairs = inject_map[idx]
            messages[idx + 1 : idx + 1] = pairs
            shift = len(pairs)
            for mention in mentions:
                try:
                    mi = int(mention.get("msg_index", -1))
                except (TypeError, ValueError):
                    continue
                if mi > idx:
                    mention["msg_index"] = mi + shift

    state["messages"] = messages
    state["mentions"] = mentions
    ctx["state"] = state
    return ctx
