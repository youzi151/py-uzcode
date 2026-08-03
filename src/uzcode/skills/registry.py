"""Runtime skill table — file packs + code-registered skills."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    # File skill: path relative to work_dir; code skill: None
    root_relpath: str | None
    source: str  # "file:<path>" | "code:<ext_name>"
    extra: dict[str, object] | None = None


class SkillRegistry:
    """Register skills; same-name later registration overwrites."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(
        self,
        name: str,
        *,
        description: str,
        body: str,
        root_relpath: str | None = None,
        source: str = "code:register",
        extra: dict[str, object] | None = None,
    ) -> None:
        self._skills[name] = Skill(
            name=name,
            description=description,
            body=body,
            root_relpath=root_relpath,
            source=source,
            extra=extra,
        )

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all(self) -> list[Skill]:
        return [self._skills[k] for k in sorted(self._skills)]

    def names(self) -> list[str]:
        return sorted(self._skills)
