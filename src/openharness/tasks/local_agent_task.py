"""Local agent task facade.

Integration: This module participates in background process/agent task state and lifecycle.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve argv safety, event-loop subprocess ownership, output locks, restart
generations, completion notification, and cleanup.
"""

from __future__ import annotations

from pathlib import Path

from openharness.tasks.manager import get_task_manager
from openharness.tasks.types import TaskRecord


async def spawn_local_agent_task(
    *,
    prompt: str,
    description: str,
    cwd: str | Path,
    model: str | None = None,
    api_key: str | None = None,
    command: str | None = None,
) -> TaskRecord:
    """Spawn a local agent subprocess task.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``create_agent_task``, ``get_task_manager``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return await get_task_manager().create_agent_task(
        prompt=prompt,
        description=description,
        cwd=cwd,
        model=model,
        api_key=api_key,
        command=command,
    )
