"""Scan project memory files.

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

from openharness.memory.paths import get_project_memory_dir
from openharness.memory.schema import (
    coerce_bool,
    coerce_int,
    coerce_optional_int,
    coerce_str_list,
    first_content_line,
    is_memory_expired,
    split_memory_file,
)
from openharness.memory.types import MemoryHeader


def scan_memory_files(
    cwd: str | Path,
    *,
    max_files: int | None = 50,
    include_disabled: bool = False,
    include_expired: bool = False,
    memory_dir: str | Path | None = None,
) -> list[MemoryHeader]:
    """Return memory headers sorted by newest first.

    Integration: Called by ``list_memory_files``, ``add_memory_entry`` and collaborates with
    ``memory_dir.glob``, ``headers.sort``, ``Path``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    exception and fallback behavior expected by callers.
    """
    memory_dir = Path(memory_dir) if memory_dir is not None else get_project_memory_dir(cwd)
    headers: list[MemoryHeader] = []
    for path in memory_dir.glob("*.md"):
        if path.name == "MEMORY.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        header = _parse_memory_file(path, text)
        if header.disabled and not include_disabled:
            continue
        if is_memory_expired(_metadata_from_header(header)) and not include_expired:
            continue
        headers.append(header)
    headers.sort(key=lambda item: item.modified_at, reverse=True)
    if max_files is None:
        return headers
    return headers[:max_files]


def _parse_memory_file(path: Path, content: str) -> MemoryHeader:
    """Parse a memory file, extracting YAML frontmatter when present.

    Integration: Called by ``scan_memory_files`` and collaborates with ``split_memory_file``,
    ``body.splitlines``, ``metadata.get``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    metadata, body, _, _ = split_memory_file(content)
    lines = body.splitlines()
    title = path.stem
    description = ""
    memory_type = ""
    if metadata.get("name"):
        title = str(metadata["name"])
    if metadata.get("description"):
        description = str(metadata["description"])
    if metadata.get("type"):
        memory_type = str(metadata["type"])

    # Fallback: first non-empty, non-frontmatter line as description
    desc_line_idx: int | None = None
    if not description:
        fallback = first_content_line("\n".join(lines[:10]))
        if fallback:
            description = fallback
        for idx, line in enumerate(lines[:10]):
            stripped = line.strip()
            if stripped[:200] == description:
                desc_line_idx = idx
                break

    # Build body preview from content after frontmatter, excluding the
    # line already used as description so search scoring stays consistent.
    body_lines = [
        line.strip()
        for idx, line in enumerate(lines)
        if line.strip()
        and not line.strip().startswith("#")
        and idx != desc_line_idx
    ]
    body_preview = " ".join(body_lines)[:300]

    return MemoryHeader(
        path=path,
        title=title,
        description=description,
        modified_at=path.stat().st_mtime,
        memory_type=memory_type,
        body_preview=body_preview,
        id=str(metadata.get("id") or ""),
        schema_version=coerce_int(metadata.get("schema_version"), default=0),
        category=str(metadata.get("category") or ""),
        importance=coerce_int(metadata.get("importance"), default=0),
        source=str(metadata.get("source") or ""),
        signature=str(metadata.get("signature") or ""),
        created_at=str(metadata.get("created_at") or ""),
        updated_at=str(metadata.get("updated_at") or ""),
        ttl_days=coerce_optional_int(metadata.get("ttl_days")),
        disabled=coerce_bool(metadata.get("disabled"), default=False),
        supersedes=coerce_str_list(metadata.get("supersedes")),
        relative_path=path.name,
        tags=coerce_str_list(metadata.get("tags")),
        frontmatter=metadata,
    )


def _metadata_from_header(header: MemoryHeader) -> dict[str, object]:
    """Extract normalized memory metadata from a document header.

    Integration: Called by ``scan_memory_files``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return {
        "created_at": header.created_at,
        "updated_at": header.updated_at,
        "ttl_days": header.ttl_days,
    }
