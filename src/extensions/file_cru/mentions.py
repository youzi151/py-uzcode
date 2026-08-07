"""file_cru mention handlers — @{file|folder[:!]:path}."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import resolve_under_work_dir

_MARK = "file_cru"
_EXPAND_CMDS = frozenset({"file", "folder"})
_PRECALL_CMDS = frozenset({"file!", "folder!"})
_FOLDER_LIST_MAX = 100


class MentionAborted(RuntimeError):
    """User chose to abort when a mention target was missing."""


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


def _work_dir(config: Any) -> Path:
    raw = getattr(config, "work_dir", None)
    if raw is None:
        raise ValueError("work_dir missing from config")
    return Path(raw)


def _rel_display(work_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(work_dir.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _file_index(work_dir: Path, path: Path) -> str:
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    rel = _rel_display(work_dir, path)
    return f"[file: {rel} | size: {stat.st_size} | mtime: {mtime}]"


def _dir_listing(path: Path) -> str:
    entries: list[str] = []
    for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
        suffix = "/" if child.is_dir() else ""
        entries.append(f"{child.name}{suffix}")
    return "\n".join(entries) if entries else "(empty)"


def _folder_index(work_dir: Path, path: Path) -> str:
    rel = _rel_display(work_dir, path)
    list_str = _dir_listing(path)
    if len(list_str) < _FOLDER_LIST_MAX:
        return f"[folder: {rel} | items: {list_str}]"
    count = len(list_str.splitlines()) if list_str != "(empty)" else 0
    return f"[folder: {rel} | items_count: {count}]"


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


def _execute_tool(
    registry: Any,
    name: str,
    arguments: dict[str, Any],
    ctx: dict[str, Any],
) -> str:
    tools = getattr(registry, "tools", None)
    if tools is None:
        raise RuntimeError(f"file_cru: tool registry unavailable for {name!r}")
    execute = getattr(tools, "execute", None)
    if execute is None:
        raise RuntimeError(f"file_cru: tools.execute unavailable for {name!r}")
    result = execute(name, arguments, ctx)
    if isinstance(result, str) and result.startswith("Error: unknown tool"):
        raise RuntimeError(f"file_cru: tool {name!r} not registered")
    return result


def _mark_handled(mention: dict[str, Any]) -> None:
    handled = list(mention.get("handled") or [])
    if _MARK not in handled:
        handled.append(_MARK)
    mention["handled"] = handled


def handle_file_mentions(ctx: dict[str, Any], registry: Any) -> dict[str, Any]:
    """Set replacement / precall tools for file and folder mention cmds."""
    state = ctx.setdefault("state", {})
    config = ctx.get("config")
    work_dir = _work_dir(config)
    messages = list(state.get("messages") or [])
    mentions = list(state.get("mentions") or [])

    tool_ctx = {
        "state": state,
        "config": config,
        "tool": {"work_dir": str(work_dir)},
        "error": None,
    }

    injections: list[tuple[int, list[dict[str, Any]]]] = []
    pending_files: set[str] = set()
    pending_dirs: set[str] = set()

    for mention in mentions:
        handled = mention.get("handled") or []
        if _MARK in handled:
            continue
        cmd = str(mention.get("cmd") or "")
        if cmd not in _EXPAND_CMDS and cmd not in _PRECALL_CMDS:
            continue

        path_text = str(mention.get("text") or "")
        raw_span = str(mention.get("raw") or "")
        try:
            resolved = resolve_under_work_dir(work_dir, path_text)
        except ValueError:
            _ask_abort(raw_span)
            _mark_handled(mention)
            continue

        base_cmd = cmd.rstrip("!")
        if base_cmd == "file":
            if not resolved.is_file():
                _ask_abort(raw_span)
                _mark_handled(mention)
                continue
            mention["replacement"] = _file_index(work_dir, resolved)
            if cmd == "file!":
                if path_text not in pending_files and not _already_tool_result(
                    messages, "read_file", "path", path_text
                ):
                    result = _execute_tool(
                        registry, "read_file", {"path": path_text}, tool_ctx
                    )
                    msg_index = int(mention.get("msg_index", -1))
                    if msg_index >= 0:
                        injections.append(
                            (
                                msg_index,
                                _synthetic_tool_pair(
                                    "read_file", {"path": path_text}, result
                                ),
                            )
                        )
                    pending_files.add(path_text)
        elif base_cmd == "folder":
            if not resolved.is_dir():
                _ask_abort(raw_span)
                _mark_handled(mention)
                continue
            mention["replacement"] = _folder_index(work_dir, resolved)
            if cmd == "folder!":
                if path_text not in pending_dirs and not _already_tool_result(
                    messages, "list_dir", "path", path_text
                ):
                    result = _execute_tool(
                        registry, "list_dir", {"path": path_text}, tool_ctx
                    )
                    msg_index = int(mention.get("msg_index", -1))
                    if msg_index >= 0:
                        injections.append(
                            (
                                msg_index,
                                _synthetic_tool_pair(
                                    "list_dir", {"path": path_text}, result
                                ),
                            )
                        )
                    pending_dirs.add(path_text)

        _mark_handled(mention)

    if injections:
        # Merge pairs for the same msg_index in original order
        inject_map: dict[int, list[dict[str, Any]]] = {}
        for idx, pairs in injections:
            inject_map.setdefault(idx, []).extend(pairs)
        # Insert from high index to low so earlier msg_index values stay valid;
        # bump mention.msg_index for messages that shift.
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
