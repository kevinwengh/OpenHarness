"""Bundled skill definitions loaded from .md files.

Integration: This module participates in instruction discovery and precedence used by runtime
prompt assembly.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve root ordering, frontmatter compatibility, project overrides, bounded
prompt metadata, and no import-time execution.
"""

from __future__ import annotations

from pathlib import Path

from openharness.skills._frontmatter import (
    optional_frontmatter_str,
    parse_bool_frontmatter,
    parse_skill_frontmatter,
    parse_skill_metadata,
)
from openharness.skills.types import SkillDefinition

_CONTENT_DIR = Path(__file__).parent / "content"


def get_bundled_skills() -> list[SkillDefinition]:
    """Load all bundled skills from the content/ directory.

    Integration: Called by ``test_skills_loaded``, ``load_skill_registry`` and collaborates with
    ``_CONTENT_DIR.exists``, ``_CONTENT_DIR.glob``, ``path.read_text``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    skills: list[SkillDefinition] = []
    if not _CONTENT_DIR.exists():
        return skills
    for path in sorted(_CONTENT_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        metadata = _parse_metadata(path.stem, content)
        display_name = metadata["name"] if metadata["name"] != path.stem else None
        skills.append(
            SkillDefinition(
                name=metadata["name"],
                description=metadata["description"],
                content=content,
                source="bundled",
                path=str(path),
                base_dir=str(path.parent),
                command_name=path.stem,
                display_name=display_name,
                user_invocable=metadata["user_invocable"],
                disable_model_invocation=metadata["disable_model_invocation"],
                model=metadata["model"],
                argument_hint=metadata["argument_hint"],
            )
        )
    return skills


def _parse_frontmatter(default_name: str, content: str) -> tuple[str, str]:
    """Extract name and description from a bundled skill markdown file.

    Delegates to the shared parser so YAML block scalars (``>``, ``|``),
    quoted values, and other standard YAML constructs are handled the same
    way as user-installed skills.

    Integration: Used as an internal helper or callback at this module boundary and collaborates
    with ``parse_skill_frontmatter``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return parse_skill_frontmatter(
        default_name,
        content,
        fallback_template="Bundled skill: {name}",
    )


def _parse_metadata(default_name: str, content: str) -> dict:
    """Parse metadata for the enclosing subsystem.

    Integration: Called by ``get_bundled_skills`` and collaborates with
    ``parse_skill_metadata``, ``parsed.get``, ``parse_bool_frontmatter``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    parsed = parse_skill_metadata(default_name, content, fallback_template="Bundled skill: {name}")
    frontmatter = parsed.get("frontmatter")
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return {
        "name": str(parsed["name"]),
        "description": str(parsed["description"]),
        "user_invocable": parse_bool_frontmatter(frontmatter.get("user-invocable"), default=True),
        "disable_model_invocation": parse_bool_frontmatter(
            frontmatter.get("disable-model-invocation"),
            default=False,
        ),
        "model": optional_frontmatter_str(frontmatter.get("model")),
        "argument_hint": optional_frontmatter_str(frontmatter.get("argument-hint")),
    }
