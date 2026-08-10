"""Shell extension — register the general-purpose ``sh`` tool."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from uzcode.tools.registry import tool_cfg

_DEFAULT_TIMEOUT = 60
_MAX_OUTPUT_CHARS = 32 * 1024

_SH_PARAMS = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "description": "Short purpose of this command (for logs and user approval)",
        },
        "command": {
            "type": "string",
            "description": "Shell command to run with cwd fixed to the work directory",
        },
    },
    "required": ["intent", "command"],
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


def make_sh_handler(config: dict[str, Any], executable: str):
    def sh(args: dict[str, Any], ctx: dict[str, Any]) -> str:
        toolcfg = tool_cfg(config, "run_shell")
        timeout_sec = toolcfg.get('timeout_sec')
        
        command = str(args.get("command", "") or "")
        if not command.strip():
            return "Error: command is required"

        work_dir = _work_dir(ctx)
        run_kwargs: dict[str, Any] = {
            "cwd": str(Path(work_dir)),
            "capture_output": True,
            "text": True,
            "errors": "replace",
        }
        if timeout_sec is not None:
            run_kwargs["timeout"] = timeout_sec
        if executable:
            run_kwargs["executable"] = executable
        try:
            completed = subprocess.run([f'"{executable}"', "-c", command], **run_kwargs)
        except subprocess.TimeoutExpired:
            return (
                f"Error: command timed out after {timeout_sec:g}s\n"
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


def make_ask_run_shell(config: dict[str, Any], executable: str):
    def ask_run_shell(arguments: dict[str, Any], ctx: dict[str, Any]) -> bool:
        """User confirmation UX for run_shell (permission=ask)."""
        toolcfg = tool_cfg(config, "run_shell")
        timeout_sec = toolcfg.get('timeout_sec')
        command = str(arguments.get("command", "") or "")
        intent = str(arguments.get("intent", "") or "").strip()
        lines = ["[run_shell] approve shell command?"]
        lines.append(f"  shell:  {executable}")
        if timeout_sec is not None:
            lines.append(f"  timeout_sec: {timeout_sec:g}")
        if intent:
            lines.append(f"  intent: {intent}")
        lines.append(f"  command: {command}")
        lines.append("Approve? (Y/n) ")
        print("\n".join(lines), file=sys.stderr, end="")
        sys.stderr.flush()
        try:
            answer = input().strip().lower()
        except EOFError:
            return False
        return answer in ("", "y", "yes")

    return ask_run_shell


def register(registry, config) -> None:
    toolcfg = tool_cfg(config, "run_shell")
    executable = _resolve_shell_executable(toolcfg)
    if executable is None:
        raise ValueError(
            "shell executable not found, need to set shell in config or "
            "environment variable SHELL"
        )

    registry.tool(
        "run_shell",
        description=(
            f"Run a shell command with cwd fixed to the work directory. "
            f"Prefer workdir-relative paths. "
            f"The active shell executable is `{executable}`. "
            f"Write commands that are syntactically valid for this specific shell."
        ),
        parameters=_SH_PARAMS,
        handler=make_sh_handler(config, executable),
        ask=make_ask_run_shell(config, executable),
    )
