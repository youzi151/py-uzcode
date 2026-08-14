"""Built-in llm_sent extension — write each outbound LLM request JSON under session/sent/."""

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
    raw = exts.get("llm_sent")
    return dict(raw) if isinstance(raw, dict) else {}


def register(registry, config) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    opts = _ext_cfg(config)
    subdir = str(opts.get("subdir") or "sent")

    def before_call_llm(ctx: dict[str, Any]) -> dict[str, Any]:
        session = ctx.get("session")
        llm_request = ctx.get("llm_request")
        if session is None or not isinstance(llm_request, dict):
            return ctx
        path_attr = getattr(session, "path", None)
        if path_attr is None:
            return ctx

        state = ctx.get("state") or {}
        try:
            iteration = int(state.get("iteration") or llm_request.get("iteration") or 0)
        except (TypeError, ValueError):
            iteration = 0

        session_dir = Path(path_attr).resolve().parent
        out_dir = session_dir / subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"sent_{stamp}_{iteration}.json"
        try:
            out_path.write_text(
                json.dumps(llm_request, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[llm_sent] failed to write {out_path}: {exc}", file=sys.stderr)
        return ctx

    registry.on("before_call_llm", before_call_llm, order=100, name="llm_sent")
