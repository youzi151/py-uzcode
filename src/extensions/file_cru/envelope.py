"""read_file result envelope helpers — hash / version / status / content."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .paths import resolve_under_work_dir

STATUS_LATEST = "LATEST"
STATUS_CHANGED = "CHANGED"
STATUS_MISSING = "MISSING"

# Legacy read_file envelopes used "OK"; treat as LATEST.
_STATUS_ALIASES = {"OK": STATUS_LATEST}


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_status(raw: Any) -> str:
    text = str(raw or STATUS_LATEST)
    return _STATUS_ALIASES.get(text, text)


def parse_envelope(raw: Any) -> dict[str, Any]:
    """Parse a read_file tool result into an envelope dict.

    Legacy plain-text results become version=1, status=LATEST, hash of the string.
    """
    if isinstance(raw, dict):
        data = raw
    else:
        text = "" if raw is None else str(raw)
        stripped = text.strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict) and "hash" in parsed and "version" in parsed:
                data = parsed
            else:
                data = None
        else:
            data = None
        if data is None:
            return {
                "hash": content_hash(text),
                "version": 1,
                "status": STATUS_LATEST,
                "content": text,
            }

    version_raw = data.get("version", 1)
    try:
        version = int(version_raw)
    except (TypeError, ValueError):
        version = 1
    content = data.get("content")
    content_s = "" if content is None else str(content)
    status = normalize_status(data.get("status"))
    digest = data.get("hash")
    if not digest:
        digest = content_hash(content_s)
    else:
        digest = str(digest)
    return {
        "hash": digest,
        "version": version,
        "status": status,
        "content": content_s,
    }


def serialize_envelope(
    *,
    digest: str,
    version: int,
    status: str,
    content: str | None,
) -> str:
    payload: dict[str, Any] = {
        "hash": digest,
        "version": int(version),
        "status": str(status),
    }
    if content is not None:
        payload["content"] = content
    return json.dumps(payload, ensure_ascii=False)


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


def _message_as_dict(msg: Any) -> dict[str, Any]:
    if isinstance(msg, dict):
        return msg
    entry: dict[str, Any] = {
        "role": getattr(msg, "role", "") or "",
        "content": getattr(msg, "content", "") or "",
    }
    name = getattr(msg, "name", None)
    if name is not None:
        entry["name"] = name
    tool_call_id = getattr(msg, "tool_call_id", None)
    if tool_call_id is not None:
        entry["tool_call_id"] = tool_call_id
    extra = getattr(msg, "extra", None)
    if isinstance(extra, dict):
        entry.update(extra)
    return entry


def _iter_named_tool_results(
    messages: list[Any], tool_name: str
) -> list[tuple[int, str, str, dict[str, Any]]]:
    """``(tool_msg_index, path, tool_call_id, payload)`` for a tool name.

    ``read_file`` payloads are full envelopes; ``file_status`` payloads are
    ``{path, version, hash, status}`` (no content).
    """
    msgs = [_message_as_dict(m) for m in messages]
    call_path: dict[str, str] = {}
    for msg in msgs:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            if fn.get("name") != tool_name:
                continue
            tc_id = str(tc.get("id") or "")
            if not tc_id:
                continue
            args = _parse_tool_args(fn.get("arguments"))
            path = str(args.get("path", "") or "")
            if path:
                call_path[tc_id] = path

    out: list[tuple[int, str, str, dict[str, Any]]] = []
    for idx, msg in enumerate(msgs):
        if msg.get("role") != "tool":
            continue
        tc_id = str(msg.get("tool_call_id") or "")
        path = call_path.get(tc_id)
        if path is None:
            continue
        raw = msg.get("content")
        if tool_name == "read_file":
            payload = parse_envelope(raw)
        else:
            payload = _parse_status_payload(raw, path)
        out.append((idx, path, tc_id, payload))
    return out


def _parse_status_payload(raw: Any, fallback_path: str) -> dict[str, Any]:
    data: dict[str, Any] | None
    if isinstance(raw, dict):
        data = raw
    else:
        text = "" if raw is None else str(raw)
        try:
            parsed = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            parsed = {}
        data = parsed if isinstance(parsed, dict) else {}
    version_raw = data.get("version", 0)
    try:
        version = int(version_raw)
    except (TypeError, ValueError):
        version = 0
    return {
        "path": str(data.get("path") or fallback_path),
        "version": version,
        "hash": str(data.get("hash") or ""),
        "status": normalize_status(data.get("status")),
    }


def iter_read_file_results(
    messages: list[Any],
) -> list[tuple[int, str, str, dict[str, Any]]]:
    """``(tool_msg_index, path, tool_call_id, envelope)`` for ``read_file``."""
    return _iter_named_tool_results(messages, "read_file")


def iter_file_status_results(
    messages: list[Any],
) -> list[tuple[int, str, str, dict[str, Any]]]:
    """``(tool_msg_index, path, tool_call_id, payload)`` for ``file_status``."""
    return _iter_named_tool_results(messages, "file_status")


def max_version_for_path(messages: list[Any], path: str) -> int:
    best = 0
    for _idx, p, _tc, env in iter_read_file_results(messages):
        if p != path:
            continue
        best = max(best, int(env.get("version") or 0))
    for _idx, p, _tc, payload in iter_file_status_results(messages):
        if p != path:
            continue
        best = max(best, int(payload.get("version") or 0))
    return best


def version_for_hash(messages: list[Any], path: str, digest: str) -> int:
    """Return existing version for ``path``+``digest``, or ``max+1`` if new."""
    digest = str(digest or "")
    if digest:
        for _idx, p, _tc, env in iter_read_file_results(messages):
            if p != path:
                continue
            if str(env.get("hash") or "") == digest:
                return int(env.get("version") or 1)
        for _idx, p, _tc, payload in iter_file_status_results(messages):
            if p != path:
                continue
            if str(payload.get("hash") or "") == digest:
                return int(payload.get("version") or 1)
    return max_version_for_path(messages, path) + 1


def latest_read_for_path(
    messages: list[Any], path: str
) -> tuple[int, dict[str, Any]] | None:
    """Return ``(tool_msg_index, envelope)`` for the highest ``read_file`` version."""
    best: tuple[int, dict[str, Any]] | None = None
    best_ver = -1
    for idx, p, _tc, env in iter_read_file_results(messages):
        if p != path:
            continue
        ver = int(env.get("version") or 0)
        if ver >= best_ver:
            best_ver = ver
            best = (idx, env)
    return best


def latest_known_for_path(
    messages: list[Any], path: str
) -> dict[str, Any] | None:
    """Highest-version snapshot among ``read_file`` and ``file_status`` for path."""
    best: dict[str, Any] | None = None
    best_ver = -1
    for _idx, p, _tc, env in iter_read_file_results(messages):
        if p != path:
            continue
        ver = int(env.get("version") or 0)
        if ver >= best_ver:
            best_ver = ver
            best = {
                "version": ver,
                "hash": str(env.get("hash") or ""),
                "status": normalize_status(env.get("status")),
                "source": "read_file",
            }
    for _idx, p, _tc, payload in iter_file_status_results(messages):
        if p != path:
            continue
        ver = int(payload.get("version") or 0)
        if ver >= best_ver:
            best_ver = ver
            best = {
                "version": ver,
                "hash": str(payload.get("hash") or ""),
                "status": normalize_status(payload.get("status")),
                "source": "file_status",
            }
    return best


def unique_read_paths(messages: list[Any]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for _idx, path, _tc, _env in iter_read_file_results(messages):
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def check_path_status(
    path: str,
    messages: list[Any],
    work_dir: Path,
) -> dict[str, Any]:
    """Report current disk status for ``path`` (no file body).

    ``status`` is ``LATEST`` if the file exists, else ``MISSING``.
    ``CHANGED`` is only for past ``read_file`` records, never for ``file_status``.
    ``version`` is keyed by content hash (same hash → same version in session).
    """
    work_dir = Path(work_dir)
    known = latest_known_for_path(messages, path)
    known_version = int(known["version"]) if known else 0

    try:
        resolved = resolve_under_work_dir(work_dir, path)
    except ValueError:
        return {
            "path": path,
            "version": known_version,
            "hash": "",
            "status": STATUS_MISSING,
        }

    if not resolved.is_file():
        return {
            "path": path,
            "version": known_version,
            "hash": "",
            "status": STATUS_MISSING,
        }

    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {
            "path": path,
            "version": known_version,
            "hash": "",
            "status": STATUS_MISSING,
        }

    current = content_hash(text)
    return {
        "path": path,
        "version": version_for_hash(messages, path, current),
        "hash": current,
        "status": STATUS_LATEST,
    }


def path_diverged_from_session(
    path: str,
    messages: list[Any],
    work_dir: Path,
) -> bool:
    """True when disk hash (or presence) differs from latest known session snapshot."""
    known = latest_known_for_path(messages, path)
    if known is None:
        return False
    known_hash = str(known.get("hash") or "")
    info = check_path_status(path, messages, work_dir)
    status = str(info.get("status") or "")
    if status == STATUS_MISSING:
        return True
    return str(info.get("hash") or "") != known_hash

