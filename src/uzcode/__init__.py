"""uzcode — a minimal, stateless AI coding agent."""

from __future__ import annotations

from pathlib import Path

from uzcode import cfg
from uzcode import engine
from uzcode.cfg import PrepareMeta
from uzcode.data import Config, Message, Session
from uzcode.extension import HookRegistry, load_extensions

__all__ = ["CodingAgent", "Config", "Message", "PrepareMeta", "Session"]


class CodingAgent:
    """Public API: prepare Config/Session from cfg+session, then run the engine."""

    def __init__(self, work_dir: str | Path = "."):
        self.work_dir = Path(work_dir).resolve()

    def prepare(
        self,
        cfg_tokens: list[str],
        session: str,
    ) -> tuple[Config, Session, PrepareMeta]:
        """Collect cfg + session via ``cfg.prepare``."""
        return cfg.prepare(self.work_dir, cfg_tokens, session)

    def load_registry(self, config: Config) -> HookRegistry:
        """Load extensions for this work_dir + config."""
        return load_extensions(self.work_dir, config)

    def act(
        self,
        config: Config,
        session: Session,
        action_names: list[str],
        *,
        registry: HookRegistry | None = None,
    ) -> tuple[Session, list[Message]]:
        """Run registered actions that may mutate ``session.messages``.

        Syncs ``session_doc`` afterward so a following ``run`` persists mutations.
        Returns ``(session, appended)`` where ``appended`` is messages added by
        actions (tail beyond the pre-act length).
        """
        if not action_names:
            return session, []

        reg = registry if registry is not None else self.load_registry(config)
        before_len = len(session.messages)

        ctx: dict = {
            "config": config,
            "session": session,
            "registry": reg,
            "action": "",
            "appended": [],
        }
        ctx = reg.run_actions(action_names, ctx)
        session = ctx.get("session", session)
        if not isinstance(session, Session):
            raise TypeError("action ctx['session'] must be a Session")

        session.sync_session_doc()

        # Prefer action-reported appends; else infer from message growth.
        reported = ctx.get("appended")
        if isinstance(reported, list) and reported:
            appended = [
                m if isinstance(m, Message) else Message.from_dict(m)
                for m in reported
            ]
        else:
            appended = list(session.messages[before_len:])
        return session, appended

    def run(
        self,
        config: Config,
        session: Session,
        *,
        registry: HookRegistry | None = None,
    ) -> tuple[Session, list[Message]]:
        """Run the agent loop. Returns session messages with this run's turns appended.
        Does not write session files — callers persist (CLI does bak/diff/session.toml).
        Session refs/messages are preserved; only assistant/tool turns are appended.
        """
        reg = registry if registry is not None else self.load_registry(config)
        return engine.run(config, session, registry=reg)
