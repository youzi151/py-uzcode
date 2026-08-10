"""Shell extension — register the general-purpose ``sh`` tool."""

from __future__ import annotations

import os
import subprocess
import sys
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


def _path_usable(raw: Any) -> str | None:
    if raw is None: return None
    text = str(raw).strip()
    if not text: return None
    path = Path(text).expanduser()

    path_posix = path.as_posix()
    if "Program Files" in path_posix:
        path_posix = path_posix.replace("Program Files", "PROGRA~1")
        path = Path(path_posix)
    if "Program Files (x86)" in path_posix:
        path_posix = path_posix.replace("Program Files (x86)", "PROGRA~2")
        path = Path(path_posix)
    
    try:
        if path.is_file():
            return path.as_posix()
    
    except OSError:
        return None
    return None

def _resolve_shell_executable(cfg: dict[str, Any]) -> str | None:
    found = _path_usable(cfg.get("shell"))
    if found is not None: return found

    found = _path_usable(os.environ.get("SHELL"))
    if found is not None: return found

    return _path_usable("/bin/sh")


def make_sh_handler(default_timeout: float, executable: str | None = None):
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
        run_kwargs: dict[str, Any] = {
            "cwd": str(Path(work_dir)),
            "capture_output": True,
            "text": True,
            "timeout": timeout_f,
            "errors": "replace",
        }
        if executable:
            run_kwargs["executable"] = executable
        try:
            completed = subprocess.run([f'"{executable}"', "-c", command], **run_kwargs)
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
    cfg = tool_cfg(config, "run_shell")
    raw_timeout = cfg.get("timeout_sec", _DEFAULT_TIMEOUT)
    try:
        default_timeout = float(raw_timeout)
    except (TypeError, ValueError):
        default_timeout = float(_DEFAULT_TIMEOUT)
    default_timeout = max(1.0, min(default_timeout, float(_MAX_TIMEOUT)))
    executable = _resolve_shell_executable(cfg)
    if executable is None:
        raise ValueError("shell executable not found, need to set shell in config or environment variable SHELL")

    registry.tool(
        "run_shell",
        description=(
            f"Run a shell command with cwd fixed to the work directory. "
            f"Prefer workdir-relative paths. "
            f"The active shell executable is `{executable}`. "
            f"Write commands that are syntactically valid for this specific shell."
        ),
        parameters=_SH_PARAMS,
        handler=make_sh_handler(default_timeout, executable),
    )
