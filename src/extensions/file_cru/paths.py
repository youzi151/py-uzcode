"""Path helpers for file_cru — confine all paths under work_dir."""

from __future__ import annotations

from pathlib import Path


def resolve_under_work_dir(work_dir: Path, path: str) -> Path:
    """Resolve path relative to work_dir; reject escapes outside work_dir."""
    if not path or not str(path).strip():
        raise ValueError("path must be a non-empty string")
    root = work_dir.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes work_dir: {path!r}") from exc
    return resolved
