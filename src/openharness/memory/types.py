"""Memory-related data models.

Integration: This module participates in durable project memory selection, indexing, migration,
and usage metadata.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve project scoping, bounded prompt content, deterministic schemas, atomic
updates, and separation from session/personal memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MemoryHeader:
    """Metadata for one memory file.

    Integration: Constructed or referenced by ``_parse_memory_file``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    path: Path
    title: str
    description: str
    modified_at: float
    memory_type: str = ""
    body_preview: str = ""
    id: str = ""
    schema_version: int = 0
    category: str = ""
    importance: int = 0
    source: str = ""
    signature: str = ""
    created_at: str = ""
    updated_at: str = ""
    ttl_days: int | None = None
    disabled: bool = False
    supersedes: tuple[str, ...] = ()
    relative_path: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    frontmatter: dict[str, Any] = field(default_factory=dict)
