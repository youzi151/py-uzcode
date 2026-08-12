"""file_cru CLI actions — file-changed / file-updated."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from uzcode.data import Message

from .envelope import (
    STATUS_CHANGED,
    check_path_status,
    iter_read_file_results,
    path_diverged_from_session,
    serialize_envelope,
    unique_read_paths,
)


def _synthetic_file_status_pair(
    path: str, *, version: int, digest: str, status: str
) -> list[Message]:
    call_id = f"action_{uuid.uuid4().hex[:24]}"
    result = json.dumps(
        {
            "path": path,
            "version": int(version),
            "hash": digest,
            "status": status,
        },
        ensure_ascii=False,
    )
    assistant = Message(
        role="assistant",
        content="",
        extra={
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "file_status",
                        "arguments": json.dumps(
                            {"path": path}, ensure_ascii=False
                        ),
                    },
                }
            ]
        },
    )
    tool = Message(
        role="tool",
        content=result,
        tool_call_id=call_id,
    )
    return [assistant, tool]


def _set_message_content(messages: list[Message], index: int, content: str) -> None:
    msg = messages[index]
    messages[index] = Message(
        role=msg.role,
        content=content,
        ref=msg.ref,
        name=msg.name,
        tool_call_id=msg.tool_call_id,
        extra=dict(msg.extra),
    )


def _mark_path_changed(
    messages: list[Message], path: str, *, clear_content: bool
) -> None:
    for idx, p, _tc, env in iter_read_file_results(messages):
        if p != path:
            continue
        updated = serialize_envelope(
            digest=str(env.get("hash") or ""),
            version=int(env.get("version") or 1),
            status=STATUS_CHANGED,
            content= env.get("content") if not clear_content else None,
        )
        _set_message_content(messages, idx, updated)


def _detect_changes(
    messages: list[Message], work_dir: Path
) -> list[tuple[str, int, str, str]]:
    """Return ``(path, version, hash, status)`` when disk diverged from session."""
    changes: list[tuple[str, int, str, str]] = []
    for path in unique_read_paths(messages):
        if not path_diverged_from_session(path, messages, work_dir):
            continue
        info = check_path_status(path, messages, work_dir)
        changes.append(
            (
                path,
                int(info.get("version", 0)),
                str(info.get("hash", "")),
                str(info.get("status", "")),
            )
        )
    return changes


def _run_file_action(ctx: dict[str, Any], *, clear_content: bool) -> dict[str, Any]:
    session = ctx.get("session")
    config = ctx.get("config")
    if session is None or config is None:
        raise ValueError("file_cru action requires ctx['session'] and ctx['config']")

    work_dir = Path(getattr(config, "work_dir"))
    messages: list[Message] = list(session.messages)
    changes = _detect_changes(messages, work_dir)
    appended: list[Message] = []

    for path, version, digest, status in changes:
        _mark_path_changed(messages, path, clear_content=clear_content)
        pair = _synthetic_file_status_pair(
            path, version=version, digest=digest, status=status
        )
        messages.extend(pair)
        appended.extend(pair)

    session.messages = messages
    ctx["session"] = session
    prior = ctx.get("appended")
    if isinstance(prior, list):
        ctx["appended"] = list(prior) + appended
    else:
        ctx["appended"] = appended
    return ctx


def act_file_changed(ctx: dict[str, Any]) -> dict[str, Any]:
    """Mark past read_file CHANGED (keep content) and inject file_status (LATEST)."""
    return _run_file_action(ctx, clear_content=False)


def act_file_updated(ctx: dict[str, Any]) -> dict[str, Any]:
    """Mark past read_file CHANGED (omit content) and inject file_status (LATEST)."""
    return _run_file_action(ctx, clear_content=True)
