"""Skills middleware handlers — read_skill / read_file_in_skill."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uzcode.skills.registry import Skill, SkillRegistry

from .paths import resolve_under_skill_root

_MAX_CONTENT_BYTES = 256 * 1024


def _work_dir(ctx: dict[str, Any]) -> Path:
    tool = ctx.get("tool") or {}
    raw = tool.get("work_dir")
    if raw is None:
        config = ctx.get("config")
        raw = getattr(config, "work_dir", None) if config is not None else None
    if raw is None:
        raise ValueError("work_dir missing from tool context")
    return Path(raw)


def _enabled_set(ctx: dict[str, Any]) -> set[str]:
    """Enabled skill names from state.skills_enabled (engine-seeded / mid-mutated)."""
    state = ctx.get("state") or {}
    enabled = state.get("skills_enabled")
    if not isinstance(enabled, list):
        return set()
    return {str(n) for n in enabled}


def _get_skill(registry: SkillRegistry, name: str, ctx: dict[str, Any]) -> Skill:
    enabled = _enabled_set(ctx)
    if name not in enabled:
        raise ValueError(f"skill {name!r} is not enabled")
    skill = registry.get(name)
    if skill is None:
        raise ValueError(f"unknown skill {name!r}")
    return skill


def make_read_skill(skills: SkillRegistry):
    def read_skill(args: dict[str, Any], ctx: dict[str, Any]) -> str:
        name = str(args.get("name", "") or "").strip()
        if not name:
            return json.dumps({"error": "name is required"})
        try:
            skill = _get_skill(skills, name, ctx)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(
            {
                "name": skill.name,
                "description": skill.description,
                "body": skill.body,
                "root_relpath": skill.root_relpath,
            },
            ensure_ascii=False,
        )

    return read_skill


def make_read_file_in_skill(skills: SkillRegistry):
    def read_file_in_skill(args: dict[str, Any], ctx: dict[str, Any]) -> str:
        name = str(args.get("name", "") or "").strip()
        path = str(args.get("path", "") or "").strip()
        if not name:
            return json.dumps({"error": "name is required"})
        if not path:
            return json.dumps({"error": "path is required"})
        try:
            skill = _get_skill(skills, name, ctx)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        if not skill.root_relpath:
            return json.dumps(
                {
                    "error": (
                        f"skill {name!r} has no disk root "
                        "(code-registered skill cannot use read_file_in_skill)"
                    )
                }
            )

        work_dir = _work_dir(ctx)
        skill_root = (work_dir / skill.root_relpath).resolve()
        try:
            resolved = resolve_under_skill_root(skill_root, path)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        if not resolved.is_file():
            return json.dumps({"error": f"not a file: {path!r}"})

        workdir_relative_path = resolved.relative_to(work_dir.resolve()).as_posix()
        size = resolved.stat().st_size
        if size > _MAX_CONTENT_BYTES:
            return json.dumps(
                {
                    "skill": name,
                    "skill_relative_path": path.replace("\\", "/"),
                    "workdir_relative_path": workdir_relative_path,
                    "size": size,
                    "content": None,
                    "hint": "file too large; use sh with workdir_relative_path",
                },
                ensure_ascii=False,
            )

        try:
            content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return json.dumps(
                {
                    "skill": name,
                    "skill_relative_path": path.replace("\\", "/"),
                    "workdir_relative_path": workdir_relative_path,
                    "size": size,
                    "content": None,
                    "hint": "binary file; use sh with workdir_relative_path",
                },
                ensure_ascii=False,
            )
        except OSError as exc:
            return json.dumps({"error": str(exc)})

        return json.dumps(
            {
                "skill": name,
                "skill_relative_path": path.replace("\\", "/"),
                "workdir_relative_path": workdir_relative_path,
                "content": content,
            },
            ensure_ascii=False,
        )

    return read_file_in_skill
