"""Skills core: registry + Agent Skills–compliant discovery."""

from uzcode.skills.discover import discover
from uzcode.skills.registry import Skill, SkillRegistry

__all__ = ["Skill", "SkillRegistry", "discover"]
