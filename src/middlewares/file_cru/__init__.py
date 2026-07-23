"""Built-in file_cru middleware — registers CRU tools + ask/approve before_tool."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import handlers
from .mentions import handle_file_mentions
from .paths import resolve_under_work_dir

_READ_PARAMS = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path relative to work_dir",
        },
    },
    "required": ["path"],
}

_LIST_PARAMS = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Directory path relative to work_dir (default: .)",
        },
    },
}

_GREP_PARAMS = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": "Python regex pattern to search for",
        },
        "path": {
            "type": "string",
            "description": "File or directory relative to work_dir (default: .)",
        },
        "max_hits": {
            "type": "integer",
            "description": "Maximum number of matching lines (default: 100)",
        },
    },
    "required": ["pattern"],
}

_WRITE_PARAMS = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path relative to work_dir",
        },
        "content": {
            "type": "string",
            "description": "Full file contents to write",
        },
    },
    "required": ["path", "content"],
}

_EDIT_PARAMS = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path relative to work_dir",
        },
        "old_string": {
            "type": "string",
            "description": "Exact unique substring to replace",
        },
        "new_string": {
            "type": "string",
            "description": "Replacement text",
        },
    },
    "required": ["path", "old_string", "new_string"],
}


def _tool_opts(config, name: str) -> dict[str, Any]:
    tools = getattr(config, "tools", None) or {}
    raw = tools.get(name) if isinstance(tools, dict) else None
    return raw if isinstance(raw, dict) else {}


def _preview_if_needed(ctx: dict[str, Any]) -> str | None:
    tool = ctx.get("tool") or {}
    name = tool.get("name")
    args = tool.get("arguments") or {}
    config = ctx.get("config")
    opts = _tool_opts(config, str(name))
    if not opts.get("preview_diff"):
        return None
    work_dir = Path(tool.get("work_dir") or config.work_dir)
    try:
        path = resolve_under_work_dir(work_dir, str(args.get("path", "")))
    except ValueError as exc:
        return f"(preview unavailable: {exc})"
    if name == "write_file":
        return handlers.preview_write_diff(path, str(args.get("content", "")))
    if name == "edit_file":
        return handlers.preview_edit_diff(
            path,
            str(args.get("old_string", "")),
            str(args.get("new_string", "")),
        )
    return None


def register(registry, config) -> None:
    registry.tool(
        "read_file",
        description="Read a text file under the work directory",
        parameters=_READ_PARAMS,
        handler=handlers.read_file,
    )
    registry.tool(
        "list_dir",
        description="List entries in a directory under the work directory",
        parameters=_LIST_PARAMS,
        handler=handlers.list_dir,
    )
    registry.tool(
        "grep",
        description="Search file contents with a regex under the work directory",
        parameters=_GREP_PARAMS,
        handler=handlers.grep,
    )
    registry.tool(
        "write_file",
        description="Create or overwrite a text file under the work directory",
        parameters=_WRITE_PARAMS,
        handler=handlers.write_file,
    )
    registry.tool(
        "edit_file",
        description="Replace a unique substring in a text file under the work directory",
        parameters=_EDIT_PARAMS,
        handler=handlers.edit_file,
    )

    def before_tool(ctx: dict[str, Any]) -> dict[str, Any]:
        # Preview only; permission=ask is handled by the engine (Y/n).
        preview = _preview_if_needed(ctx)
        if preview:
            name = (ctx.get("tool") or {}).get("name")
            print(f"[file_cru] preview for {name}:\n{preview}", file=sys.stderr)
        return ctx

    def handle_request(ctx: dict[str, Any]) -> dict[str, Any]:
        return handle_file_mentions(ctx, registry)

    registry.on("handle_request", handle_request, order=10, name="file_cru")
    registry.on("before_tool", before_tool, order=50, name="file_cru")
