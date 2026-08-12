"""Built-in skills extension — catalog via messagelib.__skill + read tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from uzcode.skills import discover

from . import handlers
from .mentions import handle_skill_mentions

CATALOG_MARKER = "<!-- uzcode:skills-catalog -->"

_READ_SKILL_PARAMS = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "Skill name from the available skills catalog",
        },
    },
    "required": ["name"],
}

_READ_FILE_PARAMS = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "Skill name from the available skills catalog",
        },
        "path": {
            "type": "string",
            "description": "Path relative to the skill root (e.g. references/REFERENCE.md)",
        },
    },
    "required": ["name", "path"],
}


def _build_catalog_block(skills: list) -> str:
    lines = [
        CATALOG_MARKER,
        "Available skills (progressive load):",
        "When a skill is relevant, call read_skill(name) to load its instructions.",
        "For files under a skill (scripts/, references/, assets/), call",
        "read_file_in_skill(name, path) — use the returned workdir_relative_path with sh.",
        "",
    ]
    if not skills:
        lines.append("(no skills enabled)")
    else:
        for skill in skills:
            lines.append(f"- {skill.name}: {skill.description}")
    lines.append("<!-- uzcode:skills-catalog-end -->")
    return "\n".join(lines)


def _skill_lib_has_catalog(messagelib: dict[str, Any]) -> bool:
    entry = messagelib.get("__skill")
    if not isinstance(entry, dict):
        return False
    return CATALOG_MARKER in str(entry.get("content") or "")


def register(registry, config) -> None:
    work_dir = Path(config.work_dir).resolve()

    name2skill = {}

    skills_dirs = [
        work_dir / ".agents" / "skills",
        work_dir / ".uzcode" / "skills",
    ]
    for skills_dir in skills_dirs:
        for skill in discover(skills_dir):
            name2skill[skill.name] = skill

    for skill in name2skill.values():
        registry.skills.register(
            skill.name,
            description=skill.description,
            body=skill.body,
            root_relpath=skill.root_relpath,
            source=skill.source,
            extra=skill.extra,
        )

    registry.tool(
        "read_skill",
        description=(
            "Load full instructions (SKILL.md body) for an enabled skill by name"
        ),
        parameters=_READ_SKILL_PARAMS,
        handler=handlers.make_read_skill(registry.skills),
    )
    registry.tool(
        "read_file_in_skill",
        description=(
            "Read a file under an enabled skill root; returns content and "
            "workdir_relative_path for use with sh; must confirm file exists"
        ),
        parameters=_READ_FILE_PARAMS,
        handler=handlers.make_read_file_in_skill(registry.skills),
    )

    def before_llm(ctx: dict[str, Any]) -> dict[str, Any]:
        state = ctx.setdefault("state", {})
        messagelib = dict(state.get("messagelib") or {})
        if _skill_lib_has_catalog(messagelib):
            return ctx

        enabled_names = [str(n) for n in (state.get("skills_enabled") or [])]
        skills = []
        for name in enabled_names:
            skill = registry.skills.get(name)
            if skill is not None:
                skills.append(skill)

        prev = messagelib.get("__skill")
        entry = dict(prev) if isinstance(prev, dict) else {}
        entry["role"] = str(entry.get("role") or "system")
        entry["content"] = _build_catalog_block(skills)
        messagelib["__skill"] = entry
        state["messagelib"] = messagelib
        return ctx

    def handle_request(ctx: dict[str, Any]) -> dict[str, Any]:
        return handle_skill_mentions(ctx, registry)

    registry.on("handle_request", handle_request, order=20, name="skills")
    registry.on("before_llm", before_llm, order=20, name="skills")
