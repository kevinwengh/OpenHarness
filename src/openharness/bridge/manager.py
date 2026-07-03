"""Track spawned bridge sessions for UI and commands.

Integration: This module participates in external command/session bridges exposed to runtime and
UI status.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve subprocess lifecycle, output files, session identity, interruption, and
cleanup.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from openharness.config.paths import get_data_dir
from openharness.bridge.session_runner import SessionHandle, spawn_session


@dataclass(frozen=True)
class BridgeSessionRecord:
    """UI-safe bridge session snapshot.

    Integration: Constructed or referenced by ``BridgeSessionManager.list_sessions``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    session_id: str
    command: str
    cwd: str
    pid: int
    status: str
    started_at: float
    output_path: str


class BridgeSessionManager:
    """Manage bridge-run child sessions and capture their output.

    Integration: Constructed or referenced by ``get_bridge_manager``.

    Event loop: Async methods ``spawn``, ``stop``, ``_copy_output`` run on their caller's loop;
    instances must retain clear task, cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self) -> None:
        """Initialize ``BridgeSessionManager`` and bind its runtime dependencies.

        Integration: Exposed through ``BridgeSessionManager``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._sessions: dict[str, SessionHandle] = {}
        self._commands: dict[str, str] = {}
        self._output_paths: dict[str, Path] = {}
        self._copy_tasks: dict[str, asyncio.Task[None]] = {}

    async def spawn(self, *, session_id: str, command: str, cwd: str | Path) -> SessionHandle:
        """Spawn and register the requested child process or session.

        Integration: Exposed through ``BridgeSessionManager`` and collaborates with
        ``output_dir.mkdir``, ``output_path.write_text``, ``asyncio.create_task``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve path isolation, encoding, and persistence side effects expected
        by callers.
        """
        handle = await spawn_session(session_id=session_id, command=command, cwd=cwd)
        self._sessions[session_id] = handle
        self._commands[session_id] = command
        output_dir = get_data_dir() / "bridge"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{session_id}.log"
        output_path.write_text("", encoding="utf-8")
        self._output_paths[session_id] = output_path
        self._copy_tasks[session_id] = asyncio.create_task(self._copy_output(session_id, handle))
        return handle

    def list_sessions(self) -> list[BridgeSessionRecord]:
        """List sessions for the enclosing subsystem.

        Integration: Called by ``create_default_command_registry``,
        ``create_default_command_registry._bridge_handler`` and collaborates with
        ``_sessions.items``, ``items.append``, ``BridgeSessionRecord``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        items: list[BridgeSessionRecord] = []
        for session_id, handle in self._sessions.items():
            process = handle.process
            if process.returncode is None:
                status = "running"
            elif process.returncode == 0:
                status = "completed"
            else:
                status = "failed"
            items.append(
                BridgeSessionRecord(
                    session_id=session_id,
                    command=self._commands.get(session_id, ""),
                    cwd=str(handle.cwd),
                    pid=process.pid or 0,
                    status=status,
                    started_at=handle.started_at,
                    output_path=str(self._output_paths[session_id]),
                )
            )
        return sorted(items, key=lambda item: item.started_at, reverse=True)

    def read_output(self, session_id: str, *, max_bytes: int = 12000) -> str:
        """Read output for the enclosing subsystem.

        Integration: Called by ``create_default_command_registry``,
        ``create_default_command_registry._bridge_handler`` and collaborates with
        ``_output_paths.get``, ``path.read_text``, ``path.exists``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve path isolation, encoding, and persistence side effects expected
        by callers.
        """
        path = self._output_paths.get(session_id)
        if path is None or not path.exists():
            return ""
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_bytes:
            return content[-max_bytes:]
        return content

    async def stop(self, session_id: str) -> None:
        """Stop the active bridge session manager lifecycle.

        Integration: Exposed through ``BridgeSessionManager`` and collaborates with
        ``ValueError``, ``handle.kill``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        handle = self._sessions.get(session_id)
        if handle is None:
            raise ValueError(f"Unknown bridge session: {session_id}")
        await handle.kill()

    async def _copy_output(self, session_id: str, handle: SessionHandle) -> None:
        """Run the copy output workflow through its asynchronous collaborators.

        Integration: Exposed through ``BridgeSessionManager`` and collaborates with
        ``handle.process.wait``, ``handle.process.stdout.read``, ``path.open``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve path isolation, encoding, and persistence side effects expected
        by callers.
        """
        path = self._output_paths[session_id]
        if handle.process.stdout is not None:
            while True:
                chunk = await handle.process.stdout.read(4096)
                if not chunk:
                    break
                with path.open("ab") as stream:
                    stream.write(chunk)
        await handle.process.wait()


_DEFAULT_MANAGER: BridgeSessionManager | None = None


def get_bridge_manager() -> BridgeSessionManager:
    """Return the singleton bridge manager.

    Integration: Called by ``create_default_command_registry``,
    ``create_default_command_registry._bridge_handler`` and collaborates with
    ``BridgeSessionManager``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    global _DEFAULT_MANAGER
    if _DEFAULT_MANAGER is None:
        _DEFAULT_MANAGER = BridgeSessionManager()
    return _DEFAULT_MANAGER
