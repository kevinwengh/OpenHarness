"""Skill registry.

Integration: This module participates in instruction discovery and precedence used by runtime
prompt assembly.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve root ordering, frontmatter compatibility, project overrides, bounded
prompt metadata, and no import-time execution.
"""

from __future__ import annotations

from openharness.skills.types import SkillDefinition


class SkillRegistry:
    """Store loaded skills by name.

    Integration: Constructed or referenced by ``load_skill_registry``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self) -> None:
        """Initialize ``SkillRegistry`` and bind its runtime dependencies.

        Integration: Exposed through ``SkillRegistry``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        """Register one skill.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        for key in (skill.name, skill.command_name, skill.display_name, *skill.aliases):
            if key:
                self._skills[key] = skill

    def get(self, name: str) -> SkillDefinition | None:
        """Return a skill by name.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self._skills.get(name)

    def list_skills(self) -> list[SkillDefinition]:
        """Return all skills sorted by name.

        Integration: Called by ``test_real_skills_loaded``, ``test_real_skill_content_quality``
        and collaborates with ``_skills.values``, ``unique.values``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        unique: dict[tuple[str, str | None], SkillDefinition] = {}
        for skill in self._skills.values():
            unique[(skill.source, skill.path or skill.name)] = skill
        return sorted(unique.values(), key=lambda skill: skill.command_name or skill.name)
