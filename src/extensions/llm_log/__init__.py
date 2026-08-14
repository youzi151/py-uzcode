"""Built-in llm_log extension — write each LLM request/response JSON under session/."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _ext_cfg(config: Any) -> dict[str, Any]:
    exts = getattr(config, "exts", None) or {}
    if not isinstance(exts, dict):
        return {}
    raw = exts.get("llm_log")
    return dict(raw) if isinstance(raw, dict) else {}


def _write_json(out_path: Path, payload: Any, label: str) -> None:
    try:
        out_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"[llm_log] failed to write {out_path}: {exc}", file=sys.stderr)
    except TypeError as exc:
        print(f"[llm_log] failed to serialize {label}: {exc}", file=sys.stderr)


def register(registry, config) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    opts = _ext_cfg(config)
    sent_subdir = str(opts.get("sent_subdir") or "sent")
    recv_subdir = str(opts.get("recv_subdir") or "recv")

    def _session_dir(ctx: dict[str, Any]) -> Path | None:
        session = ctx.get("session")
        if session is None:
            return None
        path_attr = getattr(session, "path", None)
        if path_attr is None:
            return None
        return Path(path_attr).resolve().parent

    def _iteration(ctx: dict[str, Any], payload: dict[str, Any] | None = None) -> int:
        state = ctx.get("state") or {}
        try:
            return int(
                state.get("iteration")
                or (payload or {}).get("iteration")
                or 0
            )
        except (TypeError, ValueError):
            return 0

    def before_call_llm(ctx: dict[str, Any]) -> dict[str, Any]:
        llm_request = ctx.get("llm_request")
        session_dir = _session_dir(ctx)
        if session_dir is None or not isinstance(llm_request, dict):
            return ctx
        out_dir = session_dir / sent_subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"sent_{stamp}_{_iteration(ctx, llm_request)}.json"
        _write_json(out_path, llm_request, "llm_request")
        return ctx

    def after_llm(ctx: dict[str, Any]) -> dict[str, Any]:
        llm_response = ctx.get("llm_response")
        session_dir = _session_dir(ctx)
        if session_dir is None or not isinstance(llm_response, dict):
            return ctx
        out_dir = session_dir / recv_subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"recv_{stamp}_{_iteration(ctx, llm_response)}.json"
        _write_json(out_path, llm_response, "llm_response")
        return ctx

    registry.on("before_call_llm", before_call_llm, order=100, name="llm_log")
    registry.on("after_llm", after_llm, order=100, name="llm_log")
