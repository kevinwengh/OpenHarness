"""Minimal bridge session spawner.

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
import time
from dataclasses import dataclass, field
from pathlib import Path

from openharness.utils.shell import create_shell_subprocess


@dataclass
class SessionHandle:
    """Handle for a spawned bridge session.

    Integration: Constructed or referenced by ``spawn_session``.

    Event loop: Async methods ``kill`` run on their caller's loop; instances must retain clear
    task, cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    session_id: str
    process: asyncio.subprocess.Process
    cwd: Path
    started_at: float = field(default_factory=time.time)

    async def kill(self) -> None:
        """Terminate the session process.

        Integration: Called by ``_pid_is_running``, ``stop_gateway_process`` and collaborates
        with ``process.terminate``, ``asyncio.wait_for``, ``process.wait``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=3)
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()


async def spawn_session(
    *,
    session_id: str,
    command: str,
    cwd: str | Path,
) -> SessionHandle:
    """Spawn a bridge-managed child session.

    Integration: Called by ``_run_bridge_flow``, ``BridgeSessionManager.spawn`` and collaborates
    with ``resolve``, ``SessionHandle``, ``create_shell_subprocess``.

    Event loop: This coroutine awaits subprocess work; preserve process cleanup and avoid shell-
    blocking operations.

    Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by callers.
    """
    resolved_cwd = Path(cwd).resolve()
    process = await create_shell_subprocess(
        command,
        cwd=resolved_cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    return SessionHandle(session_id=session_id, process=process, cwd=resolved_cwd)
