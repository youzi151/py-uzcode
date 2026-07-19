"""Discover Agent Skills–compliant SKILL.md packs under a skills root."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from uzcode.skills.registry import Skill

# Agent Skills name: <=64; a-z / 0-9 / -; no leading/trailing -; no --
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_NAME_LEN = 64
_MAX_DESCRIPTION_LEN = 1024


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """Split YAML frontmatter + body. Minimal parser for string scalars only."""
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None

    meta: dict[str, str] = {}
    i = 1
    while i < end:
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        # Skip nested block mappings (e.g. metadata:) — ignore unknown complexity
        if stripped.endswith(":") and ":" == stripped[-1] and stripped.count(":") == 1:
            key = stripped[:-1].strip()
            i += 1
            while i < end:
                nested = lines[i]
                if nested.startswith(" ") or nested.startswith("\t"):
                    i += 1
                    continue
                break
            # Store nothing for nested maps (unknown / optional)
            _ = key
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, raw_val = line.partition(":")
        key = key.strip()
        raw_val = raw_val.strip()
        if not key:
            i += 1
            continue
        # Quoted scalars
        if (raw_val.startswith('"') and raw_val.endswith('"')) or (
            raw_val.startswith("'") and raw_val.endswith("'")
        ):
            raw_val = raw_val[1:-1]
        meta[key] = raw_val
        i += 1

    body = "\n".join(lines[end + 1 :])
    if body.startswith("\n"):
        body = body[1:]
    return meta, body


def _valid_name(name: str) -> bool:
    if not name or len(name) > _MAX_NAME_LEN:
        return False
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return False
    return bool(_NAME_RE.fullmatch(name))


def _warn(msg: str) -> None:
    print(f"[skills] warning: {msg}", file=sys.stderr)


def discover(skills_dir: Path, *, work_dir: Path | None = None) -> list[Skill]:
    """Scan skills_dir for */SKILL.md (recursive). Skip non-compliant packs."""
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        return []

    work_dir = Path(work_dir).resolve() if work_dir is not None else skills_dir.resolve()
    found: list[Skill] = []
    seen_names: set[str] = set()

    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        if not skill_md.is_file():
            continue
        skill_root = skill_md.parent
        dir_name = skill_root.name

        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError as exc:
            _warn(f"cannot read {skill_md}: {exc}")
            continue

        parsed = _parse_frontmatter(text)
        if parsed is None:
            _warn(f"skip {skill_root}: missing or invalid YAML frontmatter")
            continue
        meta, body = parsed

        name = (meta.get("name") or "").strip()
        description = (meta.get("description") or "").strip()

        if not name:
            _warn(f"skip {skill_root}: missing required frontmatter 'name'")
            continue
        if not _valid_name(name):
            _warn(
                f"skip {skill_root}: invalid name {name!r} "
                f"(must match a-z0-9-hyphen rules, <= {_MAX_NAME_LEN})"
            )
            continue
        if name != dir_name:
            _warn(
                f"skip {skill_root}: name {name!r} != directory name {dir_name!r}"
            )
            continue
        if not description:
            _warn(f"skip {skill_root}: missing or empty required 'description'")
            continue
        if len(description) > _MAX_DESCRIPTION_LEN:
            _warn(
                f"skip {skill_root}: description longer than {_MAX_DESCRIPTION_LEN}"
            )
            continue

        try:
            root_relpath = skill_root.resolve().relative_to(work_dir).as_posix()
        except ValueError:
            root_relpath = skill_root.resolve().as_posix()

        # Optional known scalars into extra; ignore the rest
        extra: dict[str, object] = {}
        for key in ("license", "compatibility", "allowed-tools"):
            if key in meta and meta[key]:
                extra[key] = meta[key]

        if name in seen_names:
            _warn(f"duplicate skill name {name!r}; later path overwrites")
        seen_names.add(name)

        found.append(
            Skill(
                name=name,
                description=description,
                body=body,
                root_relpath=root_relpath,
                source=f"file:{root_relpath}",
                extra=extra or None,
            )
        )

    return found
