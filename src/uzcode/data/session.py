"""Load and write session TOML (full file on write-back)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import tomli_w
from dataclasses import dataclass, field


@dataclass
class Message:
    """In-memory message.

    ``content`` is the message text (authored, LLM, or tool result).
    ``ref`` names an entry in ``messagelib`` (blueprint); own fields override.
    """

    role: str = ""
    content: str = ""
    ref: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        known = {"role", "content", "ref", "name", "tool_call_id"}
        extra = {k: v for k, v in data.items() if k not in known}
        content_val = data.get("content")

        if content_val is None:
            content = ""
        else:
            content = str(content_val)
        ref_val = data.get("ref")
        ref = str(ref_val) if ref_val is not None and str(ref_val) != "" else None
        return cls(
            role=str(data.get("role") or ""),
            content=content,
            ref=ref,
            name=data.get("name"),
            tool_call_id=data.get("tool_call_id"),
            extra=extra,
        )


def copy_session_to_bak(session_dir: str | Path, stamp: str) -> Path | None:
    """Copy ``session.toml`` into ``bak/`` before a run. Returns bak path or None."""
    session_dir = Path(session_dir).resolve()
    src = session_dir / "session.toml"
    if not src.is_file():
        return None
    bak_dir = session_dir / "bak"
    bak_dir.mkdir(parents=True, exist_ok=True)
    bak_path = bak_dir / f"session_{stamp}.toml"
    shutil.copy2(src, bak_path)
    return bak_path


def persist_session(
    session_dir: str | Path,
    session: Session,
    appended: list[Message],
    *,
    stamp: str,
) -> None:
    """Write ``diff/diff_<stamp>.toml`` and overwrite session ``session.toml``.

    Session file keeps authored refs / messages / messagelib; only LLM
    assistant/tool turns are appended under ``[req].messages``.
    """
    session_dir = Path(session_dir).resolve()
    session.write(
        session_dir / "diff" / f"diff_{stamp}.toml",
        messages=appended,
        diff=True,
    )
    session.write(session_dir / "session.toml")


def _message_to_toml(msg: Message) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    if msg.ref is not None:
        entry["ref"] = msg.ref
        if msg.role:
            entry["role"] = msg.role
        if msg.content:
            entry["content"] = msg.content
    else:
        entry["role"] = msg.role
        entry["content"] = msg.content
    if msg.name is not None:
        entry["name"] = msg.name
    if msg.tool_call_id is not None:
        entry["tool_call_id"] = msg.tool_call_id
    entry.update(msg.extra)
    return entry


@dataclass
class Session:
    """Loaded session (``session.toml``) plus mutable messages for this run."""

    path: Path
    work_dir: Path
    messages: list[Message] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    session_doc: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        path: str | Path,
        work_dir: str | Path,
        data: dict[str, Any],
        *,
        session_doc: dict[str, Any] | None = None,
    ) -> Session:
        path = Path(path)
        work_dir = Path(work_dir).resolve()
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        doc = dict(session_doc) if session_doc is not None else {}
        return cls(
            path=path,
            work_dir=work_dir,
            messages=messages,
            raw=data,
            session_doc=doc,
        )

    def session_messages(self) -> list[Message]:
        """Messages authored in the session file (write-back base)."""
        req = self.session_doc.get("req")
        if not isinstance(req, dict):
            return []
        return [Message.from_dict(m) for m in req.get("messages", [])]

    def sync_session_doc(self) -> None:
        """Write ``self.messages`` into ``session_doc[req].messages``.

        Required after in-place mutations (e.g. CLI actions) so ``engine.run``
        keeps them via ``session_messages()`` + append.
        """
        req_body = dict(self.session_doc.get("req") or {})
        req_body["messages"] = [_message_to_toml(msg) for msg in self.messages]
        self.session_doc["req"] = req_body

    def write(
        self,
        path: str | Path | None = None,
        *,
        messages: list[Message] | None = None,
        diff: bool = False,
    ) -> None:
        """Write session TOML.

        Full write: entire ``session_doc`` with ``[req].messages`` updated.
        ``resp`` (last-call ``[resp.usage]``) is emitted last. Diff write: only
        ``[req].messages`` (appended turns).
        """
        out = Path(path or self.path)
        if not out.is_absolute():
            out = (self.work_dir / out).resolve()
        else:
            out = out.resolve()

        to_write = self.messages if messages is None else messages
        serialized = [_message_to_toml(msg) for msg in to_write]

        if diff:
            payload: dict[str, Any] = {"req": {"messages": serialized}}
        else:
            payload = dict(self.session_doc)
            resp = payload.pop("resp", None)
            req_body = dict(payload.get("req") or {})
            req_body["messages"] = serialized
            payload["req"] = req_body
            if resp is not None:
                payload["resp"] = resp

        text = tomli_w.dumps(payload).rstrip() + "\n"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        self.path = out
