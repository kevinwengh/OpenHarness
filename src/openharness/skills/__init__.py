"""Skill exports.

Integration: This module participates in instruction discovery and precedence used by runtime
prompt assembly.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve root ordering, frontmatter compatibility, project overrides, bounded
prompt metadata, and no import-time execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from openharness.skills.registry import SkillRegistry
    from openharness.skills.types import SkillDefinition

__all__ = [
    "SkillDefinition",
    "SkillRegistry",
    "discover_project_skill_dirs",
    "get_user_skill_dirs",
    "get_user_skills_dir",
    "load_skill_registry",
]


def __getattr__(name: str):
    """Resolve a lazily exported attribute from ``this module``.

    Integration: Used as an internal helper or callback at this module boundary and collaborates
    with ``AttributeError``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if name in {"discover_project_skill_dirs", "get_user_skill_dirs", "get_user_skills_dir", "load_skill_registry"}:
        from openharness.skills.loader import (
            discover_project_skill_dirs,
            get_user_skill_dirs,
            get_user_skills_dir,
            load_skill_registry,
        )

        return {
            "discover_project_skill_dirs": discover_project_skill_dirs,
            "get_user_skill_dirs": get_user_skill_dirs,
            "get_user_skills_dir": get_user_skills_dir,
            "load_skill_registry": load_skill_registry,
        }[name]
    if name == "SkillRegistry":
        from openharness.skills.registry import SkillRegistry

        return SkillRegistry
    if name == "SkillDefinition":
        from openharness.skills.types import SkillDefinition

        return SkillDefinition
    raise AttributeError(name)
