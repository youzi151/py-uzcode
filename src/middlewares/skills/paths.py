"""Skill-root path helpers — confine reads under a skill directory."""

from __future__ import annotations

from pathlib import Path


def resolve_under_skill_root(skill_root: Path, path: str) -> Path:
    """Resolve path relative to skill_root; reject .., absolute, and escapes."""
    if not path or not str(path).strip():
        raise ValueError("path must be a non-empty string")
    raw = str(path).strip().replace("\\", "/")
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise ValueError(f"path must be relative to skill root: {path!r}")
    parts = Path(raw).parts
    if ".." in parts:
        raise ValueError(f"path must not contain '..': {path!r}")

    root = skill_root.resolve()
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes skill root: {path!r}") from exc
    return candidate
