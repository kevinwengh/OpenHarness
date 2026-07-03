"""Usage index for recalled memory entries.

Integration: This module participates in durable project memory selection, indexing, migration,
and usage metadata.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve project scoping, bounded prompt content, deterministic schemas, atomic
updates, and separation from session/personal memory.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from openharness.memory.paths import get_project_memory_dir
from openharness.memory.scan import scan_memory_files
from openharness.memory.schema import format_datetime, parse_datetime, utc_now
from openharness.memory.types import MemoryHeader
from openharness.utils.file_lock import exclusive_file_lock
from openharness.utils.fs import atomic_write_text

USAGE_INDEX_NAME = "usage_index.json"
STALE_UNUSED_DAYS = 60
STALE_MAX_IMPORTANCE = 1


def get_usage_index_path(cwd: str | Path, *, memory_dir: str | Path | None = None) -> Path:
    """Return the usage index path for a memory store.

    Integration: Called by ``load_usage_index``, ``save_usage_index`` and collaborates with
    ``root.mkdir``, ``Path``, ``get_project_memory_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """

    root = Path(memory_dir) if memory_dir is not None else get_project_memory_dir(cwd)
    root.mkdir(parents=True, exist_ok=True)
    return root / USAGE_INDEX_NAME


def load_usage_index(cwd: str | Path, *, memory_dir: str | Path | None = None) -> dict[str, Any]:
    """Load usage index data, returning an empty index for invalid files.

    Integration: Called by ``get_memory_usage``, ``mark_memory_used`` and collaborates with
    ``get_usage_index_path``, ``data.get``, ``_empty_index``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    exception and fallback behavior expected by callers.
    """

    path = get_usage_index_path(cwd, memory_dir=memory_dir)
    if not path.exists():
        return _empty_index()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_index()
    if not isinstance(data, dict):
        return _empty_index()
    memories = data.get("memories")
    if not isinstance(memories, dict):
        memories = {}
    normalized = _empty_index()
    normalized["memories"] = {
        str(memory_id): _normalize_usage_record(record)
        for memory_id, record in memories.items()
        if isinstance(record, dict)
    }
    return normalized


def save_usage_index(
    cwd: str | Path,
    index: dict[str, Any],
    *,
    memory_dir: str | Path | None = None,
) -> None:
    """Persist usage index data atomically.

    Integration: Called by ``mark_memory_used`` and collaborates with ``get_usage_index_path``,
    ``atomic_write_text``, ``json.dumps``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    path = get_usage_index_path(cwd, memory_dir=memory_dir)
    payload = json.dumps(index, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    atomic_write_text(path, payload)


def get_memory_usage(
    cwd: str | Path,
    memory_id: str,
    *,
    memory_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return usage data for a memory id.

    Integration: Called by ``find_relevant_memories``, ``find_stale_memory_candidates`` and
    collaborates with ``load_usage_index``, ``get``, ``_normalize_usage_record``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    if not memory_id:
        return _normalize_usage_record({})
    index = load_usage_index(cwd, memory_dir=memory_dir)
    record = index["memories"].get(memory_id, {})
    return _normalize_usage_record(record)


def mark_memory_used(
    cwd: str | Path,
    memories: list[MemoryHeader],
    *,
    memory_dir: str | Path | None = None,
) -> None:
    """Record that memory entries were recalled into a runtime prompt.

    Integration: Called by ``build_runtime_system_prompt`` and collaborates with ``Path``,
    ``exclusive_file_lock``, ``load_usage_index``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers;
    retain lock scope and release behavior.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    usable = [header for header in memories if header.id]
    if not usable:
        return
    resolved_memory_dir = Path(memory_dir) if memory_dir is not None else usable[0].path.parent
    lock_path = resolved_memory_dir / ".usage_index.lock"
    with exclusive_file_lock(lock_path):
        index = load_usage_index(cwd, memory_dir=resolved_memory_dir)
        now = format_datetime(utc_now())
        for header in usable:
            record = _normalize_usage_record(index["memories"].get(header.id, {}))
            record["use_count"] = int(record["use_count"]) + 1
            record["last_used_at"] = now
            record["path"] = header.path.name
            index["memories"][header.id] = record
        save_usage_index(cwd, index, memory_dir=resolved_memory_dir)


def find_stale_memory_candidates(
    cwd: str | Path,
    *,
    memory_dir: str | Path | None = None,
) -> list[MemoryHeader]:
    """Return low-value unused memories that auto-dream should review for pruning.

    Integration: Called by ``start_dream_now`` and collaborates with ``scan_memory_files``,
    ``utc_now``, ``candidates.sort``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    resolved_memory_dir = Path(memory_dir) if memory_dir is not None else None
    headers = scan_memory_files(
        cwd,
        max_files=None,
        include_disabled=False,
        include_expired=False,
        memory_dir=resolved_memory_dir,
    )
    now = utc_now()
    candidates: list[MemoryHeader] = []
    for header in headers:
        if header.importance > STALE_MAX_IMPORTANCE:
            continue
        usage = get_memory_usage(cwd, header.id, memory_dir=resolved_memory_dir or header.path.parent)
        if int(usage["use_count"]) > 0:
            continue
        updated_at = parse_datetime(header.updated_at) or parse_datetime(header.created_at)
        if updated_at is None:
            continue
        if now - updated_at >= timedelta(days=STALE_UNUSED_DAYS):
            candidates.append(header)
    candidates.sort(key=lambda item: (item.importance, item.updated_at or "", item.path.name))
    return candidates


def _empty_index() -> dict[str, Any]:
    """Derive empty index from the current inputs and subsystem state.

    Integration: Called by ``load_usage_index``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return {"version": 1, "memories": {}}


def _normalize_usage_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize usage record for the enclosing subsystem.

    Integration: Called by ``load_usage_index``, ``get_memory_usage`` and collaborates with
    ``record.get``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    use_count = record.get("use_count", 0)
    try:
        use_count = max(0, int(use_count))
    except (TypeError, ValueError):
        use_count = 0
    return {
        "last_used_at": str(record.get("last_used_at") or ""),
        "use_count": use_count,
        "path": str(record.get("path") or ""),
    }
