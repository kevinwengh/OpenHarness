"""Paths for persistent project memory.

Integration: This module participates in durable project memory selection, indexing, migration,
and usage metadata.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve project scoping, bounded prompt content, deterministic schemas, atomic
updates, and separation from session/personal memory.
"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path

from openharness.config.paths import get_data_dir


def get_project_memory_dir(cwd: str | Path) -> Path:
    """Return the persistent memory directory for a project.

    Integration: Called by ``create_default_command_registry``,
    ``create_default_command_registry._dream_handler`` and collaborates with ``resolve``,
    ``memory_dir.mkdir``, ``hexdigest``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    path = Path(cwd).resolve()
    digest = sha1(str(path).encode("utf-8")).hexdigest()[:12]
    memory_dir = get_data_dir() / "memory" / f"{path.name}-{digest}"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir


def get_memory_entrypoint(cwd: str | Path) -> Path:
    """Return the project memory entrypoint file.

    Integration: Called by ``_memory_backend_for_context``, ``remove_memory_entry`` and
    collaborates with ``get_project_memory_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_project_memory_dir(cwd) / "MEMORY.md"
