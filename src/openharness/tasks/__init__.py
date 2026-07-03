"""Task exports.

Integration: This module participates in background process/agent task state and lifecycle.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve argv safety, event-loop subprocess ownership, output locks, restart
generations, completion notification, and cleanup.
"""

from openharness.tasks.local_agent_task import spawn_local_agent_task
from openharness.tasks.local_shell_task import spawn_shell_task
from openharness.tasks.manager import BackgroundTaskManager, get_task_manager
from openharness.tasks.stop_task import stop_task
from openharness.tasks.types import TaskRecord, TaskStatus, TaskType

__all__ = [
    "BackgroundTaskManager",
    "TaskRecord",
    "TaskStatus",
    "TaskType",
    "get_task_manager",
    "spawn_local_agent_task",
    "spawn_shell_task",
    "stop_task",
]
