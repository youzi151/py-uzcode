"""Work-dir key/value storage for extensions (``.uzcode/storage.toml``)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import tomli_w


def _split_key(key: str) -> list[str]:
    raw = str(key).strip()
    parts = raw.split(".")
    if not raw or any(p == "" for p in parts):
        raise ValueError(f"Invalid storage key {key!r}")
    return parts


def _get_dotted(root: dict[str, Any], key: str) -> tuple[bool, Any]:
    cur: Any = root
    for part in _split_key(key):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _set_dotted(root: dict[str, Any], key: str, value: Any) -> None:
    parts = _split_key(key)
    cur: dict[str, Any] = root
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


class Storage:
    """Persist TOML-serializable values under ``{work_dir}/.uzcode/storage.toml``."""

    def __init__(self, work_dir: str | Path) -> None:
        self.work_dir = Path(work_dir).resolve()
        self.path = self.work_dir / ".uzcode" / "storage.toml"

    def load(self, key: str, default: Any = None) -> Any:
        found, value = _get_dotted(self._read(), key)
        return value if found else default

    def save(self, key: str, value: Any) -> None:
        data = self._read()
        _set_dotted(data, key, value)
        self._write(data)

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        with self.path.open("rb") as f:
            data = tomllib.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"TOML root must be a table: {self.path}")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        text = tomli_w.dumps(data).rstrip() + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.path)
