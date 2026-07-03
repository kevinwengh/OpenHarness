"""Memory prompt helpers.

Integration: This module participates in durable project memory selection, indexing, migration,
and usage metadata.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve project scoping, bounded prompt content, deterministic schemas, atomic
updates, and separation from session/personal memory.
"""

from __future__ import annotations

from pathlib import Path

from openharness.memory.paths import get_memory_entrypoint, get_project_memory_dir
from openharness.memory.schema import (
    MAX_ENTRYPOINT_BYTES,
    MEMORY_POLICY_LINES,
    truncate_entrypoint_content,
)


def load_memory_prompt(
    cwd: str | Path,
    *,
    max_entrypoint_lines: int = 200,
    max_entrypoint_bytes: int = MAX_ENTRYPOINT_BYTES,
) -> str | None:
    """Return the memory prompt section for the current project.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``get_project_memory_dir``, ``get_memory_entrypoint``, ``entrypoint.exists``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    memory_dir = get_project_memory_dir(cwd)
    entrypoint = get_memory_entrypoint(cwd)
    lines = [
        "# Memory",
        f"- Persistent memory directory: {memory_dir}",
        "- Use this directory to store durable project and repository context that should survive future sessions.",
        "- Prefer concise topic files plus an index entry in MEMORY.md.",
        "",
        *MEMORY_POLICY_LINES,
    ]

    if entrypoint.exists():
        raw = entrypoint.read_text(encoding="utf-8", errors="replace")
        view = truncate_entrypoint_content(
            raw,
            max_lines=max_entrypoint_lines,
            max_bytes=max_entrypoint_bytes,
        )
        content = view.content.strip()
        if content:
            lines.extend(["", "## MEMORY.md", "```md", content, "```"])
    else:
        lines.extend(
            [
                "",
                "## MEMORY.md",
                "(not created yet)",
            ]
        )

    return "\n".join(lines)
