"""Persistent metadata for ohmo-managed chat groups.

Integration: This ohmo module specializes the reusable OpenHarness runtime with personal
workspace, memory, session, gateway, or channel behavior; core modules must not depend on it.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve the ohmo workspace boundary, conversation/session isolation, attachment
and channel contracts, credential redaction, and cleanup of per-session runtimes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any

from ohmo.workspace import get_groups_dir


@dataclass(frozen=True)
class ManagedGroupRecord:
    """Metadata for a chat group created and managed by ohmo.

    Integration: Constructed or referenced by ``save_managed_group_record``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    channel: str
    chat_id: str
    owner_open_id: str
    name: str
    created_at: str
    cwd: str | None = None
    repo: str | None = None
    binding_status: str = "pending_agent"
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_group_name(raw: str) -> str:
    """Return a safe Feishu group name from command text.

    Integration: Called by ``OhmoCreateFeishuGroupTool.execute`` and collaborates with ``join``,
    ``split``, ``ValueError``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    name = " ".join(str(raw).strip().split())
    if not name:
        raise ValueError("Group name is required.")
    if len(name) > 100:
        raise ValueError("Group name is too long; keep it within 100 characters.")
    return name


def group_record_path(
    *,
    workspace: str | Path | None,
    channel: str,
    chat_id: str,
) -> Path:
    """Return the filesystem path for group record.

    Integration: Called by ``save_managed_group_record``, ``load_managed_group_record`` and
    collaborates with ``strip``, ``get_groups_dir``, ``re.sub``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    safe_chat_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(chat_id)).strip("._") or "unknown"
    return get_groups_dir(workspace) / channel / f"{safe_chat_id}.json"


def save_managed_group_record(
    *,
    workspace: str | Path | None,
    channel: str,
    chat_id: str,
    owner_open_id: str,
    name: str,
    cwd: str | None = None,
    repo: str | None = None,
    binding_status: str = "pending_agent",
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Persist metadata for an ohmo-managed group and return the path.

    Integration: Called by ``OhmoCreateFeishuGroupTool.execute`` and collaborates with
    ``ManagedGroupRecord``, ``group_record_path``, ``path.parent.mkdir``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    record = ManagedGroupRecord(
        channel=channel,
        chat_id=chat_id,
        owner_open_id=owner_open_id,
        name=name,
        created_at=datetime.now(timezone.utc).isoformat(),
        cwd=normalize_cwd(cwd) if cwd else None,
        repo=repo,
        binding_status=binding_status,
        metadata=metadata or {},
    )
    path = group_record_path(workspace=workspace, channel=channel, chat_id=chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_managed_group_record(
    *,
    workspace: str | Path | None,
    channel: str,
    chat_id: str,
) -> dict[str, Any] | None:
    """Load metadata for an ohmo-managed group if present.

    Integration: Called by ``OhmoGatewayBridge._is_managed_feishu_group``,
    ``OhmoSessionRuntimePool._cwd_for_message`` and collaborates with ``group_record_path``,
    ``json.loads``, ``path.exists``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    path = group_record_path(workspace=workspace, channel=channel, chat_id=chat_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_cwd(cwd: str | Path) -> str:
    """Normalize a cwd binding.

    Integration: Called by ``OhmoSessionRuntimePool._cwd_for_message``,
    ``save_managed_group_record`` and collaborates with ``resolve``, ``expanduser``, ``Path``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return str(Path(cwd).expanduser().resolve())
