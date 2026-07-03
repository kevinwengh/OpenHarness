"""Relevant memory selection and formatting.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from openharness.memory.scan import scan_memory_files
from openharness.memory.schema import memory_age_label, memory_freshness_text
from openharness.memory.search import find_relevant_memories
from openharness.memory.types import MemoryHeader


@dataclass(frozen=True)
class RelevantMemory:
    """A memory selected for prompt injection.

    Integration: Constructed or referenced by ``select_relevant_memories``,
    ``select_manifest_memories``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    header: MemoryHeader
    freshness: str = ""


MemorySelector = Callable[[str, list[MemoryHeader]], list[str]]


def build_memory_manifest(headers: Iterable[MemoryHeader]) -> str:
    """Render a compact manifest for selector prompts and diagnostics.

    Integration: Called by ``build_extraction_prompt`` and collaborates with ``join``,
    ``lines.append``, ``bits.append``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    lines: list[str] = []
    for header in headers:
        prefix = f"[{header.memory_type or 'memory'}]"
        bits = [
            prefix,
            header.relative_path or header.path.name,
            f"({memory_age_label(header.modified_at)})",
        ]
        if header.description:
            bits.append(f"- {header.description}")
        lines.append(" ".join(bits))
    return "\n".join(lines)


def select_relevant_memories(
    query: str,
    cwd: str | Path,
    *,
    max_results: int = 5,
    already_surfaced: set[str] | None = None,
    selector: MemorySelector | None = None,
) -> list[RelevantMemory]:
    """Return relevant memories with duplicate and freshness handling.

    ``selector`` is an optional side-query style reranker. It receives the query
    and a heuristic shortlist, and returns relative paths in desired order.

    Integration: Called by ``build_runtime_system_prompt`` and collaborates with
    ``_apply_selector``, ``result.append``, ``find_relevant_memories``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    surfaced = already_surfaced or set()
    heuristic = [
        header
        for header in find_relevant_memories(query, cwd, max_results=max(10, max_results * 3))
        if (header.relative_path or str(header.path)) not in surfaced
    ]
    selected = _apply_selector(query, heuristic, selector=selector, max_results=max_results)
    result: list[RelevantMemory] = []
    for header in selected[:max_results]:
        result.append(RelevantMemory(header=header, freshness=memory_freshness_text(header.modified_at)))
    return result


def select_manifest_memories(
    query: str,
    cwd: str | Path,
    *,
    max_results: int = 5,
    selector: MemorySelector | None = None,
) -> list[RelevantMemory]:
    """Select from the full manifest instead of heuristic matches only.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``scan_memory_files``, ``_apply_selector``, ``RelevantMemory``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    headers = scan_memory_files(cwd, max_files=200)
    selected = _apply_selector(query, headers, selector=selector, max_results=max_results)
    return [
        RelevantMemory(header=header, freshness=memory_freshness_text(header.modified_at))
        for header in selected[:max_results]
    ]


def format_relevant_memories(memories: Iterable[RelevantMemory], *, max_chars: int = 8000) -> str:
    """Render selected memories for prompt context.

    Integration: Called by ``build_runtime_system_prompt`` and collaborates with ``join``,
    ``strip``, ``lines.extend``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """

    lines = ["# Relevant Memories"]
    for item in memories:
        header = item.header
        content = header.path.read_text(encoding="utf-8", errors="replace").strip()
        if item.freshness:
            lines.extend(["", f"## {header.relative_path or header.path.name}", f"> {item.freshness}"])
        else:
            lines.extend(["", f"## {header.relative_path or header.path.name}"])
        lines.extend(["```md", content[:max_chars], "```"])
    return "\n".join(lines)


def json_selector_from_text(text: str) -> list[str]:
    """Parse a selector response as either JSON list or newline paths.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``text.strip``, ``json.loads``, ``strip``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """

    stripped = text.strip()
    if not stripped:
        return []
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return [line.strip("- ").strip() for line in stripped.splitlines() if line.strip()]
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]
    if isinstance(payload, dict) and isinstance(payload.get("paths"), list):
        return [str(item).strip() for item in payload["paths"] if str(item).strip()]
    return []


def _apply_selector(
    query: str,
    headers: list[MemoryHeader],
    *,
    selector: MemorySelector | None,
    max_results: int,
) -> list[MemoryHeader]:
    """Apply selector for the enclosing subsystem.

    Integration: Called by ``select_relevant_memories``, ``select_manifest_memories`` and
    collaborates with ``selector``, ``by_path.get``, ``selected.append``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if not headers or selector is None:
        return headers[:max_results]
    requested = selector(query, headers)
    by_path = {header.relative_path or header.path.name: header for header in headers}
    selected: list[MemoryHeader] = []
    seen: set[str] = set()
    for path in requested:
        header = by_path.get(path)
        if header is None or path in seen:
            continue
        selected.append(header)
        seen.add(path)
    if len(selected) < max_results:
        selected.extend(
            header
            for header in headers
            if (header.relative_path or header.path.name) not in seen
        )
    return selected[:max_results]
