"""Load and write request TOML (``[request]`` section only on disk)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import tomli_w
from dataclasses import dataclass, field


@dataclass
class Message:
    """In-memory message.

    ``content`` is what goes to the LLM (may be mention-expanded).
    ``raw`` is the original text. When they differ, both are kept and
    written to TOML; when equal, only ``content`` is persisted.
    """

    role: str
    content: str
    raw: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        known = {"role", "content", "raw", "name", "tool_call_id"}
        extra = {k: v for k, v in data.items() if k not in known}
        content_val = data.get("content")
        raw_val = data.get("raw")
        if content_val is None and raw_val is None:
            content = ""
            raw = ""
        elif content_val is None:
            content = str(raw_val)
            raw = content
        elif raw_val is None:
            content = str(content_val)
            raw = content
        else:
            content = str(content_val)
            raw = str(raw_val)
        return cls(
            role=data["role"],
            content=content,
            raw=raw,
            name=data.get("name"),
            tool_call_id=data.get("tool_call_id"),
            extra=extra,
        )


def _backup_existing(out: Path, work_dir: Path) -> None:
    if not out.is_file():
        return
    bak_dir = work_dir / ".uzcode" / "outbak"
    bak_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_path = bak_dir / f"{out.name}.{stamp}.toml"
    out.replace(bak_path)


@dataclass
class Request:
    """A single agent request (``[request]`` in merged cfg / output)."""

    path: Path
    work_dir: Path
    messages: list[Message] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        path: str | Path,
        work_dir: str | Path,
        data: dict[str, Any],
    ) -> Request:
        path = Path(path)
        work_dir = Path(work_dir).resolve()
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return cls(
            path=path,
            work_dir=work_dir,
            messages=messages,
            raw=data,
        )

    def write(self, path: str | Path | None = None) -> None:
        """Write request-only TOML under ``[request]``; backup if target exists."""
        out = Path(path or self.path)
        if not out.is_absolute():
            out = (self.work_dir / out).resolve()
        else:
            out = out.resolve()

        _backup_existing(out, self.work_dir)

        messages: list[dict[str, Any]] = []
        for msg in self.messages:
            entry: dict[str, Any] = {"role": msg.role}
            if msg.raw != msg.content:
                entry["raw"] = msg.raw
            entry["content"] = msg.content
            if msg.name is not None:
                entry["name"] = msg.name
            if msg.tool_call_id is not None:
                entry["tool_call_id"] = msg.tool_call_id
            entry.update(msg.extra)
            messages.append(entry)

        body: dict[str, Any] = dict(self.raw)
        body["messages"] = messages
        text = tomli_w.dumps({"request": body}).rstrip() + "\n"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        self.path = out
