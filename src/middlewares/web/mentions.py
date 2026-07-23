"""web mention handlers — @{search|fetch[:!]:...}."""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any

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
            "raw": "",
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
            "raw": content,
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


def _execute_tool(
    registry: Any,
    name: str,
    arguments: dict[str, Any],
    ctx: dict[str, Any],
) -> str:
    tools = getattr(registry, "tools", None)
    if tools is None:
        raise RuntimeError(f"web: tool registry unavailable for {name!r}")
    execute = getattr(tools, "execute", None)
    if execute is None:
        raise RuntimeError(f"web: tools.execute unavailable for {name!r}")
    return execute(name, arguments, ctx)


def _mark_handled(mention: dict[str, Any]) -> None:
    handled = list(mention.get("handled") or [])
    if _MARK not in handled:
        handled.append(_MARK)
    mention["handled"] = handled


def _tool_args(cmd: str, text: str) -> dict[str, Any]:
    if cmd.startswith("search"):
        return {"query": text}
    return {"url": text}


def _arg_key(cmd: str) -> str:
    return "query" if cmd.startswith("search") else "url"


def handle_web_mentions(ctx: dict[str, Any], registry: Any) -> dict[str, Any]:
    """Handle search/fetch mentions when web_* tools are registered."""
    state = ctx.setdefault("state", {})
    config = ctx.get("config")
    messages = list(state.get("messages") or [])
    mentions = list(state.get("mentions") or [])

    work_dir = getattr(config, "work_dir", ".")
    tool_ctx = {
        "state": state,
        "config": config,
        "tool": {"work_dir": str(work_dir)},
        "error": None,
    }

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

        args = _tool_args(cmd, text)
        key = _arg_key(cmd)
        pend_key = (tool_name, text)

        if cmd in _EXPAND_CMDS:
            # Short index via a live tool call; keep result brief for content.
            try:
                result = _execute_tool(registry, tool_name, args, tool_ctx)
            except Exception as exc:  # noqa: BLE001
                print(f"[web] {tool_name} failed for expand: {exc}", file=sys.stderr)
                _mark_handled(mention)
                continue
            preview = result if len(result) <= 200 else result[:197] + "..."
            mention["replacement"] = f"[{cmd}: {text} | {preview}]"
        else:
            if pend_key in pending or _already_tool_result(
                messages, tool_name, key, text
            ):
                _mark_handled(mention)
                continue
            try:
                result = _execute_tool(registry, tool_name, args, tool_ctx)
            except Exception as exc:  # noqa: BLE001
                print(f"[web] {tool_name} failed for precall: {exc}", file=sys.stderr)
                _mark_handled(mention)
                continue
            msg_index = int(mention.get("msg_index", -1))
            if msg_index >= 0:
                injections.append(
                    (msg_index, _synthetic_tool_pair(tool_name, args, result))
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
