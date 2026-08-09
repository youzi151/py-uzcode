"""File CRU tool handlers (no privilege — enable/permission live in cfg + hooks)."""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any

from .envelope import (
    STATUS_LATEST,
    check_path_status,
    content_hash,
    serialize_envelope,
    version_for_hash,
)
from .paths import resolve_under_work_dir


def _work_dir(ctx: dict[str, Any]) -> Path:
    tool = ctx.get("tool") or {}
    raw = tool.get("work_dir")
    if raw is None:
        config = ctx.get("config")
        raw = getattr(config, "work_dir", None) if config is not None else None
    if raw is None:
        raise ValueError("work_dir missing from tool context")
    return Path(raw)


def read_file(args: dict[str, Any], ctx: dict[str, Any]) -> str:
    path_arg = str(args.get("path", ""))
    path = resolve_under_work_dir(_work_dir(ctx), path_arg)
    if not path.is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    text = path.read_text(encoding="utf-8")
    state = ctx.get("state") or {}
    messages = list(state.get("messages") or [])
    digest = content_hash(text)
    version = version_for_hash(messages, path_arg, digest)
    return serialize_envelope(
        digest=digest,
        version=version,
        status=STATUS_LATEST,
        content=text,
    )


def file_status(args: dict[str, Any], ctx: dict[str, Any]) -> str:
    """Report current disk status for a path (LATEST or MISSING; no content)."""
    path_arg = str(args.get("path", ""))
    if not path_arg.strip():
        raise ValueError("path is required")
    state = ctx.get("state") or {}
    messages = list(state.get("messages") or [])
    result = check_path_status(path_arg, messages, _work_dir(ctx))
    return json.dumps(result, ensure_ascii=False)


def list_dir(args: dict[str, Any], ctx: dict[str, Any]) -> str:
    path = resolve_under_work_dir(_work_dir(ctx), str(args.get("path", ".") or "."))
    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")
    entries: list[str] = []
    for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
        suffix = "/" if child.is_dir() else ""
        entries.append(f"{child.name}{suffix}")
    return "\n".join(entries) if entries else "(empty)"


def grep(args: dict[str, Any], ctx: dict[str, Any]) -> str:
    pattern = str(args.get("pattern", ""))
    if not pattern:
        raise ValueError("pattern is required")
    root = resolve_under_work_dir(
        _work_dir(ctx), str(args.get("path", ".") or ".")
    )
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Invalid regex: {exc}") from exc

    max_hits = int(args.get("max_hits", 100) or 100)
    hits: list[str] = []

    def scan_file(file_path: Path) -> None:
        nonlocal hits
        if len(hits) >= max_hits:
            return
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        rel = file_path.relative_to(_work_dir(ctx).resolve())
        for i, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                hits.append(f"{rel}:{i}:{line}")
                if len(hits) >= max_hits:
                    return

    if root.is_file():
        scan_file(root)
    elif root.is_dir():
        for file_path in sorted(root.rglob("*")):
            if file_path.is_file():
                scan_file(file_path)
                if len(hits) >= max_hits:
                    break
    else:
        raise FileNotFoundError(f"Path not found: {root}")

    if not hits:
        return "(no matches)"
    return "\n".join(hits)


def write_file(args: dict[str, Any], ctx: dict[str, Any]) -> str:
    path_str = str(args.get("path", ""))
    path = resolve_under_work_dir(_work_dir(ctx), path_str)
    content = args.get("content")
    if content is None:
        raise ValueError("content is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(content), encoding="utf-8")
    return f"Wrote {len(str(content))} chars to {path_str}"


def edit_file(args: dict[str, Any], ctx: dict[str, Any]) -> str:
    path = resolve_under_work_dir(_work_dir(ctx), str(args.get("path", "")))
    old = args.get("old_string")
    new = args.get("new_string")
    if old is None or new is None:
        raise ValueError("old_string and new_string are required")
    old_s, new_s = str(old), str(new)
    if not path.is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    text = path.read_text(encoding="utf-8")
    count = text.count(old_s)
    if count == 0:
        raise ValueError("old_string not found in file")
    if count > 1:
        raise ValueError(
            f"old_string found {count} times; must be unique for edit_file"
        )
    updated = text.replace(old_s, new_s, 1)
    path.write_text(updated, encoding="utf-8")
    return f"Updated {path} ({count} replacement)"


def preview_write_diff(path: Path, new_content: str) -> str:
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        str(new_content).splitlines(keepends=True),
        fromfile=str(path),
        tofile=str(path),
        n=3,
    )
    return "".join(diff) or "(no changes)"


def preview_edit_diff(path: Path, old_string: str, new_string: str) -> str:
    if not path.is_file():
        return f"(file missing: {path})"
    text = path.read_text(encoding="utf-8")
    if old_string not in text:
        return "(old_string not found; cannot preview)"
    updated = text.replace(old_string, new_string, 1)
    return preview_write_diff(path, updated)
