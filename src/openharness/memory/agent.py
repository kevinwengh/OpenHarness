"""Agent-scoped memory paths and snapshots.

Integration: This module participates in durable project memory selection, indexing, migration,
and usage metadata.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve project scoping, bounded prompt content, deterministic schemas, atomic
updates, and separation from session/personal memory.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Literal

from openharness.config.paths import get_data_dir
from openharness.memory.paths import get_project_memory_dir

AgentMemoryScope = Literal["user", "project", "local"]

MEMORY_INDEX = "MEMORY.md"
SNAPSHOT_DIR_NAME = "agent-memory-snapshots"


def sanitize_agent_type(agent_type: str) -> str:
    """Return a path-safe agent type.

    Integration: Called by ``get_agent_memory_dir``, ``get_agent_snapshot_dir`` and collaborates
    with ``strip``, ``re.sub``, ``agent_type.strip``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", agent_type.strip()).strip("._") or "default"


def get_agent_memory_dir(cwd: str | Path, agent_type: str, scope: AgentMemoryScope) -> Path:
    """Return an agent memory vault for the requested scope.

    Integration: Called by ``ensure_agent_memory_vault`` and collaborates with
    ``sanitize_agent_type``, ``get_data_dir``, ``get_project_memory_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    safe = sanitize_agent_type(agent_type)
    if scope == "project":
        return get_project_memory_dir(cwd) / "agent" / safe
    if scope == "local":
        return Path(cwd).resolve() / ".openharness" / "agent-memory-local" / safe
    return get_data_dir() / "agent-memory" / safe


def ensure_agent_memory_vault(cwd: str | Path, agent_type: str, scope: AgentMemoryScope) -> Path:
    """Create and return an agent-scoped memory vault.

    Integration: Called by ``_handle_memory_agent_command``, ``get_agent_memory_entrypoint`` and
    collaborates with ``get_agent_memory_dir``, ``memory_dir.mkdir``, ``entrypoint.exists``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """

    memory_dir = get_agent_memory_dir(cwd, agent_type, scope)
    memory_dir.mkdir(parents=True, exist_ok=True)
    entrypoint = memory_dir / MEMORY_INDEX
    if not entrypoint.exists():
        entrypoint.write_text("# Memory Index\n", encoding="utf-8")
    return memory_dir


def get_agent_memory_entrypoint(cwd: str | Path, agent_type: str, scope: AgentMemoryScope) -> Path:
    """Return an agent memory ``MEMORY.md`` path.

    Integration: Called by ``_handle_memory_agent_command`` and collaborates with
    ``ensure_agent_memory_vault``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    return ensure_agent_memory_vault(cwd, agent_type, scope) / MEMORY_INDEX


def get_agent_snapshot_dir(cwd: str | Path, agent_type: str) -> Path:
    """Return the project snapshot directory for an agent type.

    Integration: Called by ``initialize_agent_memory_from_snapshot`` and collaborates with
    ``sanitize_agent_type``, ``resolve``, ``Path``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    return Path(cwd).resolve() / ".openharness" / SNAPSHOT_DIR_NAME / sanitize_agent_type(agent_type)


def initialize_agent_memory_from_snapshot(
    cwd: str | Path,
    agent_type: str,
    scope: AgentMemoryScope,
    *,
    replace: bool = False,
) -> Path | None:
    """Initialize local agent memory from a project snapshot if present.

    Integration: Called by ``_handle_memory_agent_command`` and collaborates with
    ``get_agent_snapshot_dir``, ``ensure_agent_memory_vault``, ``snapshot_dir.rglob``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """

    snapshot_dir = get_agent_snapshot_dir(cwd, agent_type)
    if not snapshot_dir.exists():
        return None
    target = ensure_agent_memory_vault(cwd, agent_type, scope)
    if replace and target.exists():
        shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
    for src in snapshot_dir.rglob("*.md"):
        rel = src.relative_to(snapshot_dir)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if replace or not dest.exists() or _is_default_agent_index(dest):
            shutil.copy2(src, dest)
    return target


def _is_default_agent_index(path: Path) -> bool:
    """Return whether default agent index for the enclosing subsystem.

    Integration: Called by ``initialize_agent_memory_from_snapshot`` and collaborates with
    ``text.startswith``, ``path.read_text``, ``path.exists``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    exception and fallback behavior expected by callers.
    """
    if path.name != MEMORY_INDEX or not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return text.startswith("# Memory Index\n")
