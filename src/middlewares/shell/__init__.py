"""Shell middleware — register the general-purpose ``sh`` tool."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from uzcode.tools.registry import tool_cfg

_DEFAULT_TIMEOUT = 60
_MAX_TIMEOUT = 300
_MAX_OUTPUT_CHARS = 32 * 1024

_SH_PARAMS = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Shell command to run with cwd fixed to the work directory",
        },
        "timeout_sec": {
            "type": "number",
            "description": "Optional timeout in seconds (default from cfg or 60)",
        },
    },
    "required": ["command"],
}


def _work_dir(ctx: dict[str, Any]) -> Path:
    tool = ctx.get("tool") or {}
    raw = tool.get("work_dir")
    if raw is None:
        config = ctx.get("config")
        raw = getattr(config, "work_dir", None) if config is not None else None
    if raw is None:
        raise ValueError("work_dir missing from tool context")
    return Path(raw)


def _truncate(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[:limit] + f"\n...[truncated {omitted} chars]"


def make_sh_handler(default_timeout: float):
    def sh(args: dict[str, Any], ctx: dict[str, Any]) -> str:
        command = str(args.get("command", "") or "")
        if not command.strip():
            return "Error: command is required"

        timeout = args.get("timeout_sec")
        if timeout is None:
            timeout = default_timeout
        try:
            timeout_f = float(timeout)
        except (TypeError, ValueError):
            return "Error: timeout_sec must be a number"
        if timeout_f <= 0:
            return "Error: timeout_sec must be positive"
        timeout_f = min(timeout_f, float(_MAX_TIMEOUT))

        work_dir = _work_dir(ctx)
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=timeout_f,
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return (
                f"Error: command timed out after {timeout_f:g}s\n"
                f"command: {command}"
            )
        except OSError as exc:
            return f"Error: failed to run command: {exc}"

        stdout = _truncate(completed.stdout or "")
        stderr = _truncate(completed.stderr or "")
        parts = [
            f"exit_code: {completed.returncode}",
            "stdout:",
            stdout if stdout else "(empty)",
            "stderr:",
            stderr if stderr else "(empty)",
        ]
        return "\n".join(parts)

    return sh


def register(registry, config) -> None:
    cfg = tool_cfg(config, "sh")
    raw_timeout = cfg.get("timeout_sec", _DEFAULT_TIMEOUT)
    try:
        default_timeout = float(raw_timeout)
    except (TypeError, ValueError):
        default_timeout = float(_DEFAULT_TIMEOUT)
    default_timeout = max(1.0, min(default_timeout, float(_MAX_TIMEOUT)))

    registry.tool(
        "sh",
        description=(
            "Run a shell command with cwd fixed to the work directory. "
            "Prefer workdir-relative paths (e.g. from read_file_in_skill)."
        ),
        parameters=_SH_PARAMS,
        handler=make_sh_handler(default_timeout),
    )
