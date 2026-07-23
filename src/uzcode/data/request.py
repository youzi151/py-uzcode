"""Load and write req.toml request files."""

from __future__ import annotations

import tomllib
import tomli_w
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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


@dataclass
class Request:
    """A single agent request loaded from req.toml."""

    path: Path
    work_dir: Path
    messages: list[Message] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, req_path: str | Path, work_dir: str | Path | None = None) -> Request:
        req_path = Path(req_path)
        if not req_path.is_absolute() and work_dir is not None:
            req_path = Path(work_dir).resolve() / req_path
        else:
            req_path = req_path.resolve()

        if not req_path.is_file():
            raise FileNotFoundError(f"Request file not found: {req_path}")

        with req_path.open("rb") as f:
            raw = tomllib.load(f)

        messages = [Message.from_dict(m) for m in raw.get("messages", [])]

        return cls(
            path=req_path,
            work_dir=req_path.parent,
            messages=messages,
            raw=raw,
        )

    def write(self, path: str | Path | None = None) -> None:
        """Write request back to TOML using editable [[messages]] tables.

        Messages must be dumped as a single ``{"messages": [...]}`` document so
        nested arrays (e.g. ``tool_calls``) become ``[[messages.tool_calls]]``.
        Prefixing ``[[messages]]`` onto a per-message dump would emit top-level
        ``[[tool_calls]]`` and detach them on the next load.

        Always persist ``content``. Also persist ``raw`` when it differs.
        """

        out = Path(path or self.path)
        chunks: list[str] = []

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

        if messages:
            chunks.append(tomli_w.dumps({"messages": messages}).rstrip())

        out.write_text(("\n\n".join(chunks) + "\n") if chunks else "", encoding="utf-8")
