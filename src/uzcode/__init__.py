"""uzcode — a minimal, stateless AI coding agent."""

from __future__ import annotations

from pathlib import Path

from uzcode.data import Config, Request
from uzcode.engine import run as run_engine
from uzcode.extension import load_extensions

__all__ = ["CodingAgent", "Config", "Request"]


class CodingAgent:
    """Public API: run engine with prepared Config and Request."""

    def __init__(self, work_dir: str | Path = "."):
        self.work_dir = Path(work_dir).resolve()

    def run(self, config: Config, request: Request, *, out_path: str | Path) -> Request:
        registry = load_extensions(self.work_dir, config)
        return run_engine(config, request, out_path=out_path, registry=registry)
