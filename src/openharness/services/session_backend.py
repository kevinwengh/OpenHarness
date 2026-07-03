"""Session storage backend abstractions.

Integration: This module participates in runtime support services such as compaction, sessions,
cron, extraction, and autodream.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve persistence schemas, task/time bounds, compaction continuity,
cancellation, atomic writes, and best-effort failure boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage
from openharness.services import session_storage


class SessionBackend(Protocol):
    """Interface for persisting and restoring session state.

    Integration: Implemented by injected adapters and consumed through structural typing.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Update every implementation, injection site, and contract test when method
    signatures or ownership expectations change.
    """

    def get_session_dir(self, cwd: str | Path) -> Path:
        """Return the backing directory for session files.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """

    def save_snapshot(
        self,
        *,
        cwd: str | Path,
        model: str,
        system_prompt: str,
        messages: list[ConversationMessage],
        usage: UsageSnapshot,
        session_id: str | None = None,
        tool_metadata: dict[str, object] | None = None,
    ) -> Path:
        """Persist a session snapshot and return its path.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """

    def load_latest(self, cwd: str | Path) -> dict | None:
        """Load the latest session snapshot.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """

    def list_snapshots(self, cwd: str | Path, limit: int = 20) -> list[dict]:
        """List recent snapshots.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """

    def load_by_id(self, cwd: str | Path, session_id: str) -> dict | None:
        """Load a snapshot by ID.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """

    def export_markdown(
        self,
        *,
        cwd: str | Path,
        messages: list[ConversationMessage],
    ) -> Path:
        """Export the current transcript as markdown.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """


@dataclass(frozen=True)
class OpenHarnessSessionBackend:
    """Default session backend backed by ``~/.openharness/data/sessions``.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def get_session_dir(self, cwd: str | Path) -> Path:
        """Return session directory for the enclosing subsystem.

        Integration: Exposed through ``OpenHarnessSessionBackend`` and collaborates with
        ``session_storage.get_project_session_dir``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return session_storage.get_project_session_dir(cwd)

    def save_snapshot(
        self,
        *,
        cwd: str | Path,
        model: str,
        system_prompt: str,
        messages: list[ConversationMessage],
        usage: UsageSnapshot,
        session_id: str | None = None,
        tool_metadata: dict[str, object] | None = None,
    ) -> Path:
        """Persist snapshot for the enclosing subsystem.

        Integration: Exposed through ``OpenHarnessSessionBackend`` and collaborates with
        ``session_storage.save_session_snapshot``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return session_storage.save_session_snapshot(
            cwd=cwd,
            model=model,
            system_prompt=system_prompt,
            messages=messages,
            usage=usage,
            session_id=session_id,
            tool_metadata=tool_metadata,
        )

    def load_latest(self, cwd: str | Path) -> dict | None:
        """Load latest for the enclosing subsystem.

        Integration: Exposed through ``OpenHarnessSessionBackend`` and collaborates with
        ``session_storage.load_session_snapshot``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return session_storage.load_session_snapshot(cwd)

    def list_snapshots(self, cwd: str | Path, limit: int = 20) -> list[dict]:
        """List snapshots for the enclosing subsystem.

        Integration: Exposed through ``OpenHarnessSessionBackend`` and collaborates with
        ``session_storage.list_session_snapshots``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return session_storage.list_session_snapshots(cwd, limit=limit)

    def load_by_id(self, cwd: str | Path, session_id: str) -> dict | None:
        """Load by identifier for the enclosing subsystem.

        Integration: Exposed through ``OpenHarnessSessionBackend`` and collaborates with
        ``session_storage.load_session_by_id``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return session_storage.load_session_by_id(cwd, session_id)

    def export_markdown(
        self,
        *,
        cwd: str | Path,
        messages: list[ConversationMessage],
    ) -> Path:
        """Export markdown for the enclosing subsystem.

        Integration: Exposed through ``OpenHarnessSessionBackend`` and collaborates with
        ``session_storage.export_session_markdown``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return session_storage.export_session_markdown(cwd=cwd, messages=messages)


DEFAULT_SESSION_BACKEND: SessionBackend = OpenHarnessSessionBackend()
