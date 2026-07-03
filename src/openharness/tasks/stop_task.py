"""Stop task helper.

Integration: This module participates in background process/agent task state and lifecycle.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve argv safety, event-loop subprocess ownership, output locks, restart
generations, completion notification, and cleanup.
"""

from __future__ import annotations

from openharness.tasks.manager import get_task_manager
from openharness.tasks.types import TaskRecord


async def stop_task(task_id: str) -> TaskRecord:
    """Stop a running task via the default task manager.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``get_task_manager``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return await get_task_manager().stop_task(task_id)
