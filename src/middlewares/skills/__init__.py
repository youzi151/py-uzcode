"""Built-in skills middleware — catalog via system_messages + read tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from uzcode.skills import discover

from . import handlers

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


def _system_messages_have_catalog(system_messages: list[str]) -> bool:
    return any(CATALOG_MARKER in str(part) for part in system_messages)


def register(registry, config) -> None:
    work_dir = Path(config.work_dir).resolve()
    skills_dir = work_dir / ".uzcode" / "skills"

    for skill in discover(skills_dir, work_dir=work_dir):
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
            "workdir_relative_path for use with sh"
        ),
        parameters=_READ_FILE_PARAMS,
        handler=handlers.make_read_file_in_skill(registry.skills),
    )

    def before_llm(ctx: dict[str, Any]) -> dict[str, Any]:
        state = ctx.setdefault("state", {})
        system_messages = list(state.get("system_messages") or [])
        if _system_messages_have_catalog(system_messages):
            return ctx

        enabled_names = [str(n) for n in (state.get("skills_enabled") or [])]
        skills = []
        for name in enabled_names:
            skill = registry.skills.get(name)
            if skill is not None:
                skills.append(skill)

        system_messages.append(_build_catalog_block(skills))
        state["system_messages"] = system_messages
        return ctx

    registry.on("before_llm", before_llm, order=20, name="skills")
