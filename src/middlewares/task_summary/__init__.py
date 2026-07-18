"""Built-in task_summary middleware — summarize_task tool + on_result open."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import handlers

_SUMMARIZE_PARAMS = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": (
                "Concise narrative of what was accomplished and how "
                "(for the user, after the request is done)"
            ),
        },
        "next_steps": {
            "type": "string",
            "description": (
                "Optional remaining work or suggested follow-ups; "
                "omit or leave empty if nothing remains"
            ),
        },
    },
    "required": ["summary"],
}

_TOOL_DESCRIPTION = (
    "Call once when the current user request is finished (or blocked with a "
    "clear outcome). Writes a markdown task summary for the user covering the "
    "request, what was done, tools used, and optional next steps. Ends the "
    "agent loop after this turn."
)


def _auto_open_enabled(config: Any) -> bool:
    cfg = handlers.mid_cfg(config)
    if "auto_open" not in cfg:
        return True
    return bool(cfg.get("auto_open"))


def _open_path(path: Path) -> None:
    target = str(path)
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", target], check=False)
    else:
        subprocess.run(["xdg-open", target], check=False)


def register(registry, config) -> None:
    registry.tool(
        "summarize_task",
        description=_TOOL_DESCRIPTION,
        parameters=_SUMMARIZE_PARAMS,
        handler=handlers.summarize_task,
    )

    def on_result(ctx: dict[str, Any]) -> dict[str, Any]:
        if not _auto_open_enabled(ctx.get("config")):
            return ctx
        extra = (ctx.get("state") or {}).get("extra") or {}
        if not isinstance(extra, dict):
            return ctx
        raw = extra.get("task_summary_file")
        if not raw:
            return ctx
        path = Path(str(raw))
        if not path.is_file():
            return ctx
        try:
            _open_path(path)
        except OSError as exc:
            print(
                f"[task_summary] failed to open {path}: {exc}",
                file=sys.stderr,
            )
        return ctx

    registry.on("on_result", on_result, order=100, name="task_summary")
