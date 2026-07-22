"""task_summary tool handler — hybrid report + unique markdown file."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_OUT_DIR = ".uzcode/summaries"
_REQUEST_PREVIEW = 500
_ARGS_PREVIEW = 120
_RESULT_PREVIEW = 120
_TOOL_NAME = "summarize_task"


def mid_cfg(config: Any) -> dict[str, Any]:
    middleware = getattr(config, "middleware", None) or {}
    if not isinstance(middleware, dict):
        return {}
    raw = middleware.get("task_summary")
    return raw if isinstance(raw, dict) else {}


def _work_dir(ctx: dict[str, Any]) -> Path:
    tool = ctx.get("tool") or {}
    raw = tool.get("work_dir")
    if raw is None:
        config = ctx.get("config")
        raw = getattr(config, "work_dir", None) if config is not None else None
    if raw is None:
        raise ValueError("work_dir missing from tool context")
    return Path(raw)


def _resolve_under_work_dir(work_dir: Path, path: str) -> Path:
    if not path or not str(path).strip():
        raise ValueError("path must be a non-empty string")
    root = work_dir.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes work_dir: {path!r}") from exc
    return resolved


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _args_preview(arguments: Any) -> str:
    if isinstance(arguments, str):
        raw = arguments
    else:
        try:
            raw = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            raw = str(arguments)
    return _truncate(raw.replace("\n", " "), _ARGS_PREVIEW)


def _last_user_content(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def _tool_results_by_id(messages: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        call_id = str(msg.get("tool_call_id") or "")
        if call_id:
            out[call_id] = str(msg.get("content") or "")
    return out


def _collect_tools_used(messages: list[dict[str, Any]]) -> list[str]:
    results = _tool_results_by_id(messages)
    lines: list[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            if not name or name == _TOOL_NAME:
                continue
            call_id = str(tc.get("id") or "")
            args_raw = fn.get("arguments")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except (json.JSONDecodeError, TypeError):
                args = args_raw
            line = f"- `{name}` args={_args_preview(args)}"
            if call_id and call_id in results:
                line += f" → {_truncate(results[call_id].replace(chr(10), ' '), _RESULT_PREVIEW)}"
            lines.append(line)
    return lines


def _format_markdown(
    *,
    request: str,
    summary: str,
    tools_used: list[str],
    next_steps: str,
) -> str:
    parts = [
        "# Task summary",
        "",
        "## Request",
        "",
        _truncate(request, _REQUEST_PREVIEW) or "(none)",
        "",
        "## What was done",
        "",
        summary.strip() or "(none)",
        "",
        "## Tools used",
        "",
    ]
    if tools_used:
        parts.extend(tools_used)
    else:
        parts.append("(none)")
    if next_steps.strip():
        parts.extend(["", "## Next steps", "", next_steps.strip()])
    parts.append("")
    return "\n".join(parts)


def _unique_summary_path(out_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = uuid.uuid4().hex[:8]
    return out_dir / f"summary_{stamp}_{short}.md"


def summarize_task(args: dict[str, Any], ctx: dict[str, Any]) -> str:
    summary = str(args.get("summary") or "").strip()
    if not summary:
        raise ValueError("summary is required")
    next_steps = str(args.get("next_steps") or "").strip()

    state = ctx.setdefault("state", {})
    messages = list(state.get("messages") or [])
    request = _last_user_content(messages)
    tools_used = _collect_tools_used(messages)
    body = _format_markdown(
        request=request,
        summary=summary,
        tools_used=tools_used,
        next_steps=next_steps,
    )

    work_dir = _work_dir(ctx)
    cfg = mid_cfg(ctx.get("config"))
    out_rel = str(cfg.get("task_summary_path") or _DEFAULT_OUT_DIR).strip() or _DEFAULT_OUT_DIR
    out_dir = _resolve_under_work_dir(work_dir, out_rel)
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = _unique_summary_path(out_dir)
    file_path.write_text(body, encoding="utf-8")

    extra = state.setdefault("extra", {})
    if not isinstance(extra, dict):
        raise TypeError("state.extra must be a dict")
    resolved = str(file_path.resolve())
    extra["task_summary_file"] = resolved
    state["stop_loop"] = True

    print(f"[task_summary] wrote {out_rel}", file=sys.stdout)
    return f"Task summary written to {out_rel}. It will open when the run finishes (if auto_open)."
