"""uzcode — a minimal, stateless AI coding agent."""

from __future__ import annotations

from pathlib import Path

from uzcode import cfg
from uzcode import engine
from uzcode.cfg import PrepareMeta
from uzcode.data import Config, Message, Request
from uzcode.extension import load_extensions

__all__ = ["CodingAgent", "Config", "Message", "PrepareMeta", "Request"]


class CodingAgent:
    """Public API: prepare Config/Request from cfg+session, then run the engine."""

    def __init__(self, work_dir: str | Path = "."):
        self.work_dir = Path(work_dir).resolve()

    def prepare(
        self,
        cfg_tokens: list[str],
        session: str,
    ) -> tuple[Config, Request, PrepareMeta]:
        """Collect cfg + session via ``cfg.prepare``."""
        return cfg.prepare(self.work_dir, cfg_tokens, session)

    def run(
        self,
        config: Config,
        request: Request,
    ) -> tuple[Request, list[Message]]:
        """Run the agent loop. Returns session messages with this run's turns appended.

        Does not write session files — callers persist (CLI does reqbak/diffs/request.toml).
        Session refs/messages are preserved; only assistant/tool turns are appended.
        """
        registry = load_extensions(self.work_dir, config)
        return engine.run(config, request, registry=registry)
