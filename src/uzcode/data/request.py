"""Load and write req.toml request files."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Message:
    role: str
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        known = {"role", "content", "name", "tool_call_id"}
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            role=data["role"],
            content=data.get("content", ""),
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
        """Write request back to TOML (used in Phase 1+)."""
        import tomli_w

        out = path or self.path
        out = Path(out)

        data: dict[str, Any] = dict(self.raw)
        data["messages"] = []
        for msg in self.messages:
            entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.name is not None:
                entry["name"] = msg.name
            if msg.tool_call_id is not None:
                entry["tool_call_id"] = msg.tool_call_id
            entry.update(msg.extra)
            data["messages"].append(entry)

        with out.open("wb") as f:
            tomli_w.dump(data, f)
