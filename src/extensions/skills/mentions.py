"""skills mention handlers — @{skill|skill!:name}."""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any

_MARK = "skills"
_EXPAND_CMDS = frozenset({"skill"})
_PRECALL_CMDS = frozenset({"skill!"})
_DESC_MAX = 50


def _skill_index(name: str, skill: Any) -> str:
    desc = str(getattr(skill, "description", "") or "")
    if desc and len(desc) < _DESC_MAX:
        return f"[skill: {name} | desc: {desc}]"
    return f"[skill: {name}]"


class MentionAborted(RuntimeError):
    """User chose to abort when a skill mention target was missing."""


def _ask_abort(mention: str) -> None:
    print(
        f"Mention target missing: {mention!r} - continue? (y/N) ",
        file=sys.stderr,
        end="",
        flush=True,
    )
    try:
        answer = input().strip().lower()
    except EOFError:
        answer = "n"
    if answer in ("", "n", "no"):
        raise MentionAborted(f"mention: aborted by user for missing {mention!r}")


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


def _already_read_skill(messages: list[dict[str, Any]], name: str) -> bool:
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") != "read_skill":
                continue
            args = _parse_tool_args(fn.get("arguments"))
            if str(args.get("name", "")) != name:
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


def _execute_tool(
    registry: Any,
    name: str,
    arguments: dict[str, Any],
    ctx: dict[str, Any],
) -> str:
    tools = getattr(registry, "tools", None)
    if tools is None:
        raise RuntimeError(f"skills: tool registry unavailable for {name!r}")
    execute = getattr(tools, "execute", None)
    if execute is None:
        raise RuntimeError(f"skills: tools.execute unavailable for {name!r}")
    result = execute(name, arguments, ctx)
    if isinstance(result, str) and result.startswith("Error: unknown tool"):
        raise RuntimeError(f"skills: tool {name!r} not registered")
    return result


def _mark_handled(mention: dict[str, Any]) -> None:
    handled = list(mention.get("handled") or [])
    if _MARK not in handled:
        handled.append(_MARK)
    mention["handled"] = handled


def _is_enabled_skill(name: str, state: dict[str, Any], skills_registry: Any) -> bool:
    enabled = {str(n) for n in (state.get("skills_enabled") or [])}
    if name not in enabled:
        return False
    if skills_registry is None:
        return False
    get = getattr(skills_registry, "get", None)
    if get is None:
        return False
    return get(name) is not None


def handle_skill_mentions(ctx: dict[str, Any], registry: Any) -> dict[str, Any]:
    """Set replacement / precall read_skill for skill mention cmds."""
    state = ctx.setdefault("state", {})
    config = ctx.get("config")
    messages = list(state.get("messages") or [])
    mentions = list(state.get("mentions") or [])
    skills_registry = getattr(registry, "skills", None)

    work_dir = getattr(config, "work_dir", ".")
    tool_ctx = {
        "state": state,
        "config": config,
        "tool": {"work_dir": str(work_dir)},
        "error": None,
    }

    injections: list[tuple[int, list[dict[str, Any]]]] = []
    pending: set[str] = set()

    for mention in mentions:
        handled = mention.get("handled") or []
        if _MARK in handled:
            continue
        cmd = str(mention.get("cmd") or "")
        if cmd not in _EXPAND_CMDS and cmd not in _PRECALL_CMDS:
            continue

        name = str(mention.get("text") or "").strip()
        raw_span = str(mention.get("raw") or "")
        if not name or not _is_enabled_skill(name, state, skills_registry):
            _ask_abort(raw_span)
            _mark_handled(mention)
            continue

        skill = skills_registry.get(name)
        mention["replacement"] = _skill_index(name, skill)
        if cmd == "skill!":
            if name not in pending and not _already_read_skill(messages, name):
                result = _execute_tool(
                    registry, "read_skill", {"name": name}, tool_ctx
                )
                msg_index = int(mention.get("msg_index", -1))
                if msg_index >= 0:
                    injections.append(
                        (
                            msg_index,
                            _synthetic_tool_pair(
                                "read_skill", {"name": name}, result
                            ),
                        )
                    )
                pending.add(name)

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
