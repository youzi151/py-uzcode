"""Scan and expand @ / # mentions in user messages."""

from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import resolve_under_work_dir

_AT_RE = re.compile(r"(?<![\w])@([^\s@#]+)")
_HASH_RE = re.compile(r"(?<![\w])#([^\s@#]+)")
_FOLDER_LIST_MAX = 100


class MentionAborted(RuntimeError):
    """User chose to abort when a mention target was missing."""


def _ask_abort(mention: str) -> None:
    """Ask whether to abort. y/Enter = continue; N = abort."""
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


def _folder_expand(work_dir: Path, path: Path) -> str:
    rel = _rel_display(work_dir, path)
    list_str = _dir_listing(path)
    if len(list_str) < _FOLDER_LIST_MAX:
        return f"[folder: {rel} | items: {list_str}]"
    return f"[folder: {rel} | items_count: {len(listing)}]"


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


def _already_read_file(messages: list[dict[str, Any]], path: str) -> bool:
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") != "read_file":
                continue
            args = _parse_tool_args(fn.get("arguments"))
            if str(args.get("path", "")) != path:
                continue
            tc_id = tc.get("id")
            if any(
                m.get("role") == "tool" and m.get("tool_call_id") == tc_id
                for m in messages
            ):
                return True
    return False


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


def _expand_at_in_text(text: str, work_dir: Path) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(1)
        mention = f"@{token}"
        try:
            resolved = resolve_under_work_dir(work_dir, token)
        except ValueError:
            _ask_abort(mention)
            return mention
        if resolved.is_file():
            return _file_index(work_dir, resolved)
        if resolved.is_dir():
            return _folder_expand(work_dir, resolved)
        _ask_abort(mention)
        return mention

    return _AT_RE.sub(repl, text)


def _is_skill(token: str, state: dict[str, Any], skills_registry: Any) -> bool:
    enabled = state.get("skills_enabled") or []
    if token not in {str(n) for n in enabled}:
        return False
    if skills_registry is None:
        return False
    get = getattr(skills_registry, "get", None)
    if get is None:
        return False
    return get(token) is not None


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
        raise RuntimeError(f"mention: tool registry unavailable for {name!r}")
    execute = getattr(tools, "execute", None)
    if execute is None:
        raise RuntimeError(f"mention: tools.execute unavailable for {name!r}")
    result = execute(name, arguments, ctx)
    if isinstance(result, str) and result.startswith("Error: unknown tool"):
        raise RuntimeError(
            f"mention: tool {name!r} not registered "
            f"(enable file_cru / skills middleware)"
        )
    return result


def expand_mentions(ctx: dict[str, Any], registry: Any) -> dict[str, Any]:
    """Mutate state messages: expand @ tokens; preload # via synthetic tools."""
    state = ctx.get("state") or {}
    config = ctx.get("config")
    work_dir = _work_dir(config)
    messages = list(state.get("messages") or [])
    skills_registry = getattr(registry, "skills", None)

    # Pass 1: expand @ in all user messages
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, str) or "@" not in content:
            continue
        msg["content"] = _expand_at_in_text(content, work_dir)

    # Pass 2: collect # injections (skip already-read / already queued this pass)
    injections: list[tuple[int, list[dict[str, Any]]]] = []
    pending_files: set[str] = set()
    pending_skills: set[str] = set()
    tool_ctx = {
        "state": state,
        "config": config,
        "tool": {"work_dir": str(work_dir)},
        "error": None,
    }

    for idx, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, str) or "#" not in content:
            continue

        seen_in_msg: set[str] = set()
        pairs: list[dict[str, Any]] = []

        for match in _HASH_RE.finditer(content):
            token = match.group(1)
            if token in seen_in_msg:
                continue
            seen_in_msg.add(token)
            mention = f"#{token}"

            if _is_skill(token, state, skills_registry):
                if token in pending_skills or _already_read_skill(messages, token):
                    continue
                result = _execute_tool(
                    registry, "read_skill", {"name": token}, tool_ctx
                )
                pairs.extend(
                    _synthetic_tool_pair("read_skill", {"name": token}, result)
                )
                pending_skills.add(token)
                continue

            # Treat as file path
            if token in pending_files or _already_read_file(messages, token):
                continue
            try:
                resolved = resolve_under_work_dir(work_dir, token)
            except ValueError:
                _ask_abort(mention)
                continue
            if not resolved.is_file():
                _ask_abort(mention)
                continue
            result = _execute_tool(
                registry, "read_file", {"path": token}, tool_ctx
            )
            pairs.extend(_synthetic_tool_pair("read_file", {"path": token}, result))
            pending_files.add(token)

        if pairs:
            injections.append((idx, pairs))

    if injections:
        new_messages: list[dict[str, Any]] = []
        inject_map = {i: pairs for i, pairs in injections}
        for idx, msg in enumerate(messages):
            new_messages.append(msg)
            if idx in inject_map:
                new_messages.extend(inject_map[idx])
        messages = new_messages

    state["messages"] = messages
    ctx["state"] = state
    return ctx
