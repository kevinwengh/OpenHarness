"""Personal memory helpers for ``.ohmo``.

Integration: This ohmo module specializes the reusable OpenHarness runtime with personal
workspace, memory, session, gateway, or channel behavior; core modules must not depend on it.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve the ohmo workspace boundary, conversation/session isolation, attachment
and channel contracts, credential redaction, and cleanup of per-session runtimes.
"""

from __future__ import annotations

from pathlib import Path
from re import fullmatch, sub

from openharness.commands import MemoryCommandBackend
from openharness.memory.scan import scan_memory_files
from openharness.memory.schema import (
    SCHEMA_VERSION,
    coerce_int,
    compute_memory_signature,
    first_content_line,
    format_datetime,
    generate_memory_id,
    memory_metadata_from_path,
    render_memory_file,
    split_memory_file,
    utc_now,
)
from openharness.utils.file_lock import exclusive_file_lock
from openharness.utils.fs import atomic_write_text

from ohmo.workspace import get_memory_dir, get_memory_index_path


def list_memory_files(workspace: str | Path | None = None) -> list[Path]:
    """List ``.ohmo`` memory markdown files.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``get_memory_dir``, ``scan_memory_files``, ``_scan_cwd``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    memory_dir = get_memory_dir(workspace)
    return sorted(
        header.path
        for header in scan_memory_files(
            _scan_cwd(workspace, memory_dir),
            max_files=None,
            memory_dir=memory_dir,
        )
    )


def add_memory_entry(
    workspace: str | Path | None,
    title: str,
    content: str,
    *,
    namespace: str | None = None,
    source: str = "manual",
) -> Path:
    """Create a personal memory file and append it to ``MEMORY.md``.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``get_memory_dir``, ``memory_dir.mkdir``, ``strip``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers;
    retain lock scope and release behavior.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    memory_dir = get_memory_dir(workspace)
    memory_dir.mkdir(parents=True, exist_ok=True)
    slug = sub(r"[^a-zA-Z0-9]+", "_", title.strip().lower()).strip("_") or "memory"
    with exclusive_file_lock(memory_dir / ".memory.lock"):
        memory_type = "personal"
        category = "preference"
        body = content.strip() + "\n"
        signature = compute_memory_signature(body, memory_type, category)
        existing = scan_memory_files(
            _scan_cwd(workspace, memory_dir),
            max_files=None,
            include_disabled=True,
            include_expired=True,
            memory_dir=memory_dir,
        )
        namespace_key = namespace.strip().lower() if namespace else None
        if namespace_key and not fullmatch(r"[a-z][a-z0-9._-]{0,127}", namespace_key):
            raise ValueError("memory namespace must be a lowercase identifier")
        exact = (
            next(
                (
                    header
                    for header in existing
                    if _memory_identity(header.path) == (namespace_key, title.strip())
                ),
                None,
            )
            if namespace_key is not None
            else None
        )
        duplicate = (
            next(
                (
                    header
                    for header in existing
                    if _memory_namespace(header.path) is None
                    and _effective_signature(header.path, header.signature) == signature
                ),
                None,
            )
            if namespace_key is None
            else None
        )
        target = exact or duplicate
        file_slug = f"{namespace_key}_{slug}" if namespace_key else slug
        path = target.path if target is not None else _next_memory_path(memory_dir, file_slug)
        now = utc_now()
        now_text = format_datetime(now)
        if path.exists():
            metadata, old_body, _, _ = split_memory_file(path.read_text(encoding="utf-8"))
            metadata = memory_metadata_from_path(
                path,
                metadata,
                old_body,
                now=now,
                source=str(metadata.get("source") or source),
                default_type=memory_type,
                default_category=category,
            )
            created_at = str(metadata.get("created_at") or now_text)
            memory_id = str(metadata.get("id") or generate_memory_id(now))
        else:
            metadata = {}
            created_at = now_text
            memory_id = generate_memory_id(now)
        metadata.update(
            {
                "schema_version": SCHEMA_VERSION,
                "id": memory_id,
                "name": title.strip(),
                "description": first_content_line(body) or title.strip(),
                "type": str(metadata.get("type") or memory_type),
                "category": str(metadata.get("category") or category),
                "importance": max(coerce_int(metadata.get("importance"), default=0), 1),
                "source": source,
                "signature": signature,
                "created_at": created_at,
                "updated_at": now_text,
                "ttl_days": metadata.get("ttl_days"),
                "disabled": False,
                "supersedes": metadata.get("supersedes") or [],
            }
        )
        if namespace_key:
            metadata["namespace"] = namespace_key
        atomic_write_text(path, render_memory_file(metadata, body))

        index_path = get_memory_index_path(workspace)
        existing_index = index_path.read_text(encoding="utf-8") if index_path.exists() else "# Memory Index\n"
        if path.name not in existing_index:
            label = f"{namespace_key}: {title}" if namespace_key else title
            existing_index = existing_index.rstrip() + f"\n- [{label}]({path.name})\n"
            atomic_write_text(index_path, existing_index)
    return path


def remove_memory_entry(workspace: str | Path | None, name: str) -> bool:
    """Soft-delete a memory file and remove its index entry.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``get_memory_dir``, ``exclusive_file_lock``, ``path.read_text``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers;
    retain lock scope and release behavior.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    memory_dir = get_memory_dir(workspace)
    matches = [
        header
        for header in scan_memory_files(
            _scan_cwd(workspace, memory_dir),
            max_files=None,
            include_disabled=True,
            include_expired=True,
            memory_dir=memory_dir,
        )
        if name in {header.path.stem, header.path.name, header.title, header.id}
    ]
    if not matches:
        return False
    header = matches[0]
    if header.disabled:
        return False
    path = header.path
    with exclusive_file_lock(memory_dir / ".memory.lock"):
        content = path.read_text(encoding="utf-8")
        metadata, body, _, _ = split_memory_file(content)
        metadata = memory_metadata_from_path(
            path,
            metadata,
            body,
            source="manual",
            default_type="personal",
            default_category="preference",
        )
        metadata["disabled"] = True
        metadata["updated_at"] = format_datetime(utc_now())
        atomic_write_text(path, render_memory_file(metadata, body))

        index_path = get_memory_index_path(workspace)
        if index_path.exists():
            lines = [
                line
                for line in index_path.read_text(encoding="utf-8").splitlines()
                if path.name not in line
            ]
            atomic_write_text(index_path, "\n".join(lines).rstrip() + "\n")
    return True


def load_memory_prompt(workspace: str | Path | None = None, *, max_files: int = 5) -> str | None:
    """Return a prompt section describing personal memory.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``get_memory_dir``, ``get_memory_index_path``, ``index_path.exists``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    memory_dir = get_memory_dir(workspace)
    index_path = get_memory_index_path(workspace)
    lines = [
        "# ohmo Memory",
        f"- Personal memory directory: {memory_dir}",
        "- Use this memory for stable user preferences and durable personal context.",
    ]

    if index_path.exists():
        index_lines = index_path.read_text(encoding="utf-8").splitlines()[:200]
        lines.extend(["", "## MEMORY.md", "```md", *index_lines, "```"])

    for path in list_memory_files(workspace)[:max_files]:
        content = path.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            continue
        lines.extend(["", f"## {path.name}", "```md", content[:4000], "```"])

    return "\n".join(lines)


def create_memory_command_backend(workspace: str | Path | None = None) -> MemoryCommandBackend:
    """Return a ``/memory`` backend bound to ohmo's personal memory store.

    Integration: Called by ``OhmoSessionRuntimePool.get_bundle``,
    ``OhmoSessionRuntimePool.stream_message`` and collaborates with ``MemoryCommandBackend``,
    ``get_memory_dir``, ``get_memory_index_path``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    return MemoryCommandBackend(
        label="ohmo personal memory",
        default_type="personal",
        default_category="preference",
        get_memory_dir=lambda: get_memory_dir(workspace),
        get_entrypoint=lambda: get_memory_index_path(workspace),
        list_files=lambda: list_memory_files(workspace),
        add_entry=lambda title, content: add_memory_entry(workspace, title, content),
        remove_entry=lambda name: remove_memory_entry(workspace, name),
    )


def _scan_cwd(workspace: str | Path | None, memory_dir: Path) -> Path:
    """Scan working directory for the enclosing subsystem.

    Integration: Called by ``list_memory_files``, ``add_memory_entry`` and collaborates with
    ``Path``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return Path(workspace) if workspace is not None else memory_dir.parent


def _next_memory_path(memory_dir: Path, slug: str) -> Path:
    """Return the filesystem path for next memory.

    Integration: Used as an internal helper or callback at this module boundary and collaborates
    with ``path.exists``, ``candidate.exists``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    path = memory_dir / f"{slug}.md"
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = memory_dir / f"{slug}_{index}.md"
        if not candidate.exists():
            return candidate
        index += 1


def _effective_signature(path: Path, existing_signature: str) -> str:
    """Derive effective signature from the current inputs and subsystem state.

    Integration: Used as an internal helper or callback at this module boundary and collaborates
    with ``compute_memory_signature``, ``split_memory_file``, ``path.read_text``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    exception and fallback behavior expected by callers.
    """
    if existing_signature:
        return existing_signature
    try:
        metadata, body, _, _ = split_memory_file(path.read_text(encoding="utf-8"))
    except OSError:
        return ""
    memory_type = str(metadata.get("type") or "personal")
    category = str(metadata.get("category") or "preference")
    return compute_memory_signature(body, memory_type, category)


def _memory_namespace(path: Path) -> str | None:
    """Read the optional namespace participating in automation upsert identity."""

    try:
        metadata, _, _, _ = split_memory_file(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    value = metadata.get("namespace")
    return str(value).strip() if value else None


def _memory_identity(path: Path) -> tuple[str | None, str]:
    """Return the namespace/title identity used only for namespaced upserts."""

    try:
        metadata, _, _, _ = split_memory_file(path.read_text(encoding="utf-8"))
    except OSError:
        return (None, "")
    namespace = metadata.get("namespace")
    name = metadata.get("name")
    return (
        str(namespace).strip() if namespace else None,
        str(name).strip() if name else "",
    )
