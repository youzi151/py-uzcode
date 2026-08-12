"""Resolve cfg / session paths, expand layers, and prepare Config + Request."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from overdict import merge

import uzcode
from uzcode.data import Config, Request

_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def resolve_cfg_path(work_dir: str | Path, token: str) -> Path:
    """Resolve a cfg token to a TOML file path.

    Order: existing user path → ``{work_dir}/.uzcode/cfgs/{name}.toml`` →
    built-in ``uzcode/cfgs/{name}.toml``. Extension ``.toml`` is optional.
    """
    work_dir = Path(work_dir).resolve()
    raw = token.strip()
    name = raw[:-5] if raw.lower().endswith(".toml") else raw

    candidates: list[Path] = []
    as_path = Path(raw)
    if as_path.is_absolute():
        candidates.append(as_path)
    else:
        candidates.append(Path.cwd() / raw)
        candidates.append(work_dir / raw)
        if raw != name:
            candidates.append(Path.cwd() / name)
            candidates.append(work_dir / name)
        else:
            candidates.append(Path.cwd() / f"{name}.toml")
            candidates.append(work_dir / f"{name}.toml")

    for path in candidates:
        if path.is_file():
            return path.resolve()

    project = work_dir / ".uzcode" / "cfgs" / f"{name}.toml"
    if project.is_file():
        return project.resolve()

    builtin = Path(uzcode.__file__).resolve().parent / "cfgs" / f"{name}.toml"
    if builtin.is_file():
        return builtin.resolve()

    raise FileNotFoundError(
        f"Config not found for {token!r}. Tried user path, "
        f"{project}, and built-in {builtin}."
    )


def resolve_session_dir(work_dir: str | Path, name: str) -> Path:
    """Resolve session name to ``{work_dir}/.uzcode/sessions/<name>/``."""
    work_dir = Path(work_dir).resolve()
    raw = name.strip()
    if not raw or not _SESSION_NAME_RE.fullmatch(raw):
        raise ValueError(
            f"Invalid session name {name!r}. Use a single path segment "
            f"(letters, digits, ., _, -; must start with alphanumeric)."
        )
    session_dir = (work_dir / ".uzcode" / "sessions" / raw).resolve()
    sessions_root = (work_dir / ".uzcode" / "sessions").resolve()
    if session_dir.parent != sessions_root:
        raise ValueError(f"Invalid session name {name!r}.")
    return session_dir


def load_toml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with path.open("rb") as f:
        data = tomllib.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"TOML root must be a table: {path}")
    return data


def _normalize_cfg_insert(value: Any, path: Path) -> list[str]:
    if isinstance(value, str):
        tokens = [value]
    elif isinstance(value, list):
        tokens = value
    else:
        raise ValueError(
            f"cfg_insert in {path} must be a string or list of strings"
        )
    if not tokens:
        raise ValueError(f"cfg_insert in {path} must not be empty")
    out: list[str] = []
    for item in tokens:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"cfg_insert in {path} must contain only non-empty strings"
            )
        out.append(item.strip())
    return out


def _expand_cfg_token(
    work_dir: Path,
    token: str,
    out_paths: list[Path],
    out_cfg_dicts: list[dict[str, Any]],
    exist_stack: list[Path] = [],
) -> None:
    """Expand one cfg token into the flat layer lists.

    ``cfg_insert`` lists are spliced before this file's own dict (meta key
    stripped). Alias-only files (``cfg_insert`` alone) contribute no layer.
    Re-entering a path already on the expansion stack raises.
    """
    path = resolve_cfg_path(work_dir, token)
    if path in exist_stack:
        trail = " -> ".join(str(p) for p in (*exist_stack, path))
        raise ValueError(f"cfg_insert cycle: {trail}")

    data = load_toml(path)
    exist_stack.append(path)
    try:
        if "cfg_insert" not in data:
            out_paths.append(path)
            out_cfg_dicts.append(data)
            return

        for sub in _normalize_cfg_insert(data["cfg_insert"], path):
            _expand_cfg_token(work_dir, sub, out_paths, out_cfg_dicts, exist_stack)

        rest = {k: v for k, v in data.items() if k != "cfg_insert"}
        if rest:
            out_paths.append(path)
            out_cfg_dicts.append(rest)
    finally:
        exist_stack.pop()


def expand_cfg_layers(
    work_dir: Path,
    tokens: list[str],
) -> tuple[list[Path], list[dict[str, Any]]]:
    """Resolve cfg tokens, expand ``cfg_insert`` lists, return flat layers.

    Each ``cfg_insert`` splices those cfgs into the layer list before the current
    file's remaining fields. Nested ``cfg_insert`` is allowed. Cycles (re-entering
    a path on the current expansion stack) raise ``ValueError``.
    """
    work_dir = Path(work_dir).resolve()
    paths: list[Path] = []
    cfg_dicts: list[dict[str, Any]] = []

    for token in tokens:
        _expand_cfg_token(work_dir, token, paths, cfg_dicts)

    return paths, cfg_dicts


@dataclass(frozen=True)
class PrepareMeta:
    """Metadata from cfg.prepare for CLI preview / persist."""

    session_dir: Path
    session_path: Path
    cfg_paths: list[Path]


def prepare(
    work_dir: str | Path,
    cfg_tokens: list[str],
    session: str,
) -> tuple[Config, Request, PrepareMeta]:
    """Collect cfg layers with session ``session.toml`` as the last layer.

    ``session.toml`` is treated as a normal cfg file (may contribute
    ``[request]`` via overdict merge with earlier ``--cfg`` layers).
    """
    work_dir = Path(work_dir).resolve()
    session_dir = resolve_session_dir(work_dir, session)
    session_path = session_dir / "session.toml"
    if not session_path.is_file():
        raise FileNotFoundError(
            f"Session file not found: {session_path}. "
            f"Create the file under .uzcode/sessions/<name>/session.toml"
        )

    tokens = list(cfg_tokens) + [str(session_path)]
    paths, cfg_dicts = expand_cfg_layers(work_dir, tokens)
    if not cfg_dicts:
        raise ValueError("cfg layers must not be empty after expand")

    session_doc = load_toml(session_path)

    merged = dict(merge(*cfg_dicts))
    req_raw = merged.pop("req", None)
    if not isinstance(req_raw, dict):
        req_raw = {}

    config = Config.from_dict(work_dir, merged)
    request = Request.from_dict(
        session_path,
        work_dir,
        req_raw,
        session_doc=session_doc,
    )
    meta = PrepareMeta(
        session_dir=session_dir,
        session_path=session_path,
        cfg_paths=paths,
    )
    return config, request, meta
