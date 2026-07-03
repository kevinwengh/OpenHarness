"""Background task manager.

Integration: This module participates in background process/agent task state and lifecycle.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve argv safety, event-loop subprocess ownership, output locks, restart
generations, completion notification, and cleanup.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

from openharness.config.paths import get_tasks_dir
from openharness.tasks.types import TaskRecord, TaskStatus, TaskType
from openharness.utils.shell import create_shell_subprocess

log = logging.getLogger(__name__)
_TASK_RESTART_NOTICE = "[OpenHarness] Agent task restarted; prior interactive context was not preserved.\n"


def _encode_task_worker_payload(data: str) -> bytes:
    """Serialize one worker input as a single JSON line.

    Plain-text prompts may contain embedded newlines, so they cannot be written
    directly to a readline()-based worker protocol. We wrap them in a JSON
    object with a ``text`` field, while preserving already-structured payloads
    emitted by teammate backends.

    Integration: Called by ``BackgroundTaskManager.write_to_task`` and collaborates with
    ``data.rstrip``, ``encode``, ``json.loads``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """

    stripped = data.rstrip("\n")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict) and isinstance(payload.get("text"), str):
        framed = stripped
    elif "\n" not in stripped and "\r" not in stripped:
        framed = stripped
    else:
        framed = json.dumps({"text": stripped}, ensure_ascii=False)
    return (framed + "\n").encode("utf-8")

CompletionListener = Callable[[TaskRecord], Awaitable[None] | None]


class BackgroundTaskManager:
    """Manage shell and agent subprocess tasks.

    Integration: Constructed or referenced by ``get_task_manager``.

    Event loop: Async methods ``create_shell_task``, ``create_agent_task``, ``stop_task``,
    ``write_to_task`` run on their caller's loop; instances must retain clear task,
    cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self) -> None:
        """Initialize ``BackgroundTaskManager`` and bind its runtime dependencies.

        Integration: Exposed through ``BackgroundTaskManager``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._tasks: dict[str, TaskRecord] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._waiters: dict[str, asyncio.Task[None]] = {}
        self._output_locks: dict[str, asyncio.Lock] = {}
        self._input_locks: dict[str, asyncio.Lock] = {}
        self._generations: dict[str, int] = {}
        self._completion_listeners: dict[str, CompletionListener] = {}

    async def create_shell_task(
        self,
        *,
        command: str | None = None,
        description: str,
        cwd: str | Path,
        task_type: TaskType = "local_bash",
        env: dict[str, str] | None = None,
        argv: list[str] | None = None,
    ) -> TaskRecord:
        """Start a background command.

        Either ``command`` (a shell-evaluated string) or ``argv`` (a direct
        argv list) must be supplied. The ``argv`` form bypasses shell
        invocation entirely — it spawns the executable directly via
        ``asyncio.create_subprocess_exec(*argv)`` — which is the right choice
        for teammate spawning on Windows: Git Bash cannot reliably exec
        Windows-pathed binaries (e.g. ``C:\\Users\\...\\python.exe``) when it
        is itself launched via ``create_subprocess_exec`` with that path
        embedded in a ``-lc`` string, even though the same shell call works
        interactively. Bypassing the shell sidesteps that entire class of
        platform-quoting bug.

        ``env`` is merged with ``os.environ`` when the subprocess is launched,
        so callers should pass only the variables they want to add or
        override.

        Integration: Called by ``create_default_command_registry``,
        ``create_default_command_registry._tasks_handler`` and collaborates with ``_task_id``,
        ``TaskRecord``, ``output_path.write_text``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O; retain lock scope and release behavior.

        Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
        exception and fallback behavior expected by callers.
        """
        if command is None and argv is None:
            raise ValueError("create_shell_task requires either command or argv")
        if command is not None and argv is not None:
            raise ValueError("create_shell_task accepts only one of command or argv")
        task_id = _task_id(task_type)
        output_path = get_tasks_dir() / f"{task_id}.log"
        record = TaskRecord(
            id=task_id,
            type=task_type,
            status="running",
            description=description,
            cwd=str(Path(cwd).resolve()),
            output_file=output_path,
            command=command,
            created_at=time.time(),
            started_at=time.time(),
            env=dict(env) if env is not None else None,
            argv=list(argv) if argv is not None else None,
        )
        output_path.write_text("", encoding="utf-8")
        self._tasks[task_id] = record
        self._output_locks[task_id] = asyncio.Lock()
        self._input_locks[task_id] = asyncio.Lock()
        await self._start_process(task_id)
        return record

    async def create_agent_task(
        self,
        *,
        prompt: str,
        description: str,
        cwd: str | Path,
        task_type: TaskType = "local_agent",
        model: str | None = None,
        api_key: str | None = None,
        command: str | None = None,
        env: dict[str, str] | None = None,
        argv: list[str] | None = None,
    ) -> TaskRecord:
        """Start a local agent task as a subprocess.

        Prefer ``argv`` (direct exec, no shell) over ``command`` (shell-
        evaluated) for teammate spawn — see :meth:`create_shell_task` for
        the cross-platform reasoning. ``env`` is forwarded to
        :meth:`create_shell_task` and ultimately merged with ``os.environ``
        at process spawn time.

        Integration: Called by ``SubprocessBackend.spawn``, ``spawn_local_agent_task`` and
        collaborates with ``replace``, ``create_shell_task``, ``write_to_task``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract; preserve
        exception and fallback behavior expected by callers.
        """
        if command is None and argv is None:
            effective_api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not effective_api_key:
                raise ValueError(
                    "Local agent tasks require ANTHROPIC_API_KEY or an explicit command/argv override"
                )
            argv = ["python", "-m", "openharness", "--api-key", effective_api_key]
            if model:
                argv.extend(["--model", model])

        record = await self.create_shell_task(
            command=command,
            description=description,
            cwd=cwd,
            task_type=task_type,
            env=env,
            argv=argv,
        )
        updated = replace(record, prompt=prompt)
        if task_type != "local_agent":
            updated.metadata["agent_mode"] = task_type
        self._tasks[record.id] = updated
        await self.write_to_task(record.id, prompt)
        return updated

    def get_task(self, task_id: str) -> TaskRecord | None:
        """Return one task record.

        Integration: Called by ``create_default_command_registry``,
        ``create_default_command_registry._dream_handler`` and collaborates with ``_tasks.get``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self._tasks.get(task_id)

    def list_tasks(self, *, status: TaskStatus | None = None) -> list[TaskRecord]:
        """Return all tasks, optionally filtered by status.

        Integration: Called by ``create_default_command_registry``,
        ``create_default_command_registry._stats_handler`` and collaborates with
        ``_tasks.values``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        tasks = list(self._tasks.values())
        if status is not None:
            tasks = [task for task in tasks if task.status == status]
        return sorted(tasks, key=lambda item: item.created_at, reverse=True)

    def update_task(
        self,
        task_id: str,
        *,
        description: str | None = None,
        progress: int | None = None,
        status_note: str | None = None,
    ) -> TaskRecord:
        """Update mutable task metadata used for coordination and UI display.

        Integration: Called by ``create_default_command_registry``,
        ``create_default_command_registry._tasks_handler`` and collaborates with
        ``_require_task``, ``description.strip``, ``status_note.strip``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        task = self._require_task(task_id)
        if description is not None and description.strip():
            task.description = description.strip()
        if progress is not None:
            task.metadata["progress"] = str(progress)
        if status_note is not None:
            note = status_note.strip()
            if note:
                task.metadata["status_note"] = note
            else:
                task.metadata.pop("status_note", None)
        return task

    async def stop_task(self, task_id: str) -> TaskRecord:
        """Terminate a running task.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_require_task``, ``_processes.get``, ``process.terminate``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        task = self._require_task(task_id)
        process = self._processes.get(task_id)
        if process is None:
            if task.status in {"completed", "failed", "killed"}:
                return task
            raise ValueError(f"Task {task_id} is not running")

        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        await _close_process_stdin(process)

        task.status = "killed"
        task.ended_at = time.time()
        await self._notify_completion_listeners(task)
        return task

    async def write_to_task(self, task_id: str, data: str) -> None:
        """Write one line to task stdin, auto-resuming local agents when needed.

        Integration: Called by ``SubprocessBackend.send_message``,
        ``BackgroundTaskManager.create_agent_task`` and collaborates with ``_require_task``,
        ``_encode_task_worker_payload``, ``process.stdin.write``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        task = self._require_task(task_id)
        payload = _encode_task_worker_payload(data)
        async with self._input_locks[task_id]:
            process = await self._ensure_writable_process(task)
            process.stdin.write(payload)
            try:
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                if task.type not in {"local_agent", "remote_agent", "in_process_teammate"}:
                    raise ValueError(f"Task {task_id} does not accept input") from None
                process = await self._restart_agent_task(task)
                process.stdin.write(payload)
                await process.stdin.drain()

    def read_task_output(self, task_id: str, *, max_bytes: int = 12000) -> str:
        """Return the tail of a task's output file.

        Integration: Called by ``create_default_command_registry``,
        ``create_default_command_registry._agents_handler`` and collaborates with
        ``_require_task``, ``task.output_file.read_text``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve path isolation, encoding, and persistence side effects expected
        by callers.
        """
        task = self._require_task(task_id)
        content = task.output_file.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_bytes:
            return content[-max_bytes:]
        return content

    def register_completion_listener(self, listener: CompletionListener) -> Callable[[], None]:
        """Register a callback fired whenever a task reaches a terminal state.

        Integration: Called by ``_ensure_listener_registered``, ``start_dream_now`` and
        collaborates with ``uuid4``, ``_completion_listeners.pop``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        listener_id = uuid4().hex
        self._completion_listeners[listener_id] = listener

        def _unregister() -> None:
            """Apply unregister to the enclosing subsystem state.

            Integration: Used as an internal helper or callback at this module boundary and
            collaborates with ``_completion_listeners.pop``.

            Concurrency: This is synchronous; preserve deterministic behavior for its direct
            callers.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            self._completion_listeners.pop(listener_id, None)

        return _unregister

    async def _watch_process(
        self,
        task_id: str,
        process: asyncio.subprocess.Process,
        generation: int,
    ) -> None:
        """Run the watch process workflow through its asynchronous collaborators.

        Integration: Called by ``BackgroundTaskManager._start_process`` and collaborates with
        ``asyncio.create_task``, ``_generations.get``, ``time.time``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        reader = asyncio.create_task(self._copy_output(task_id, process))
        return_code = await process.wait()
        await reader
        await _close_process_stdin(process)

        current_generation = self._generations.get(task_id)
        if current_generation != generation:
            return

        task = self._tasks[task_id]
        task.return_code = return_code
        if task.status != "killed":
            task.status = "completed" if return_code == 0 else "failed"
        task.ended_at = time.time()
        await self._notify_completion_listeners(task)
        self._processes.pop(task_id, None)
        self._waiters.pop(task_id, None)

    async def _copy_output(self, task_id: str, process: asyncio.subprocess.Process) -> None:
        """Run the copy output workflow through its asynchronous collaborators.

        Integration: Exposed through ``BackgroundTaskManager`` and collaborates with
        ``process.stdout.read``, ``output_file.open``, ``handle.write``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve path isolation, encoding, and persistence side effects expected
        by callers.
        """
        if process.stdout is None:
            return
        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                return
            async with self._output_locks[task_id]:
                with self._tasks[task_id].output_file.open("ab") as handle:
                    handle.write(chunk)

    def _require_task(self, task_id: str) -> TaskRecord:
        """Derive require task from the current inputs and subsystem state.

        Integration: Called by ``BackgroundTaskManager.update_task``,
        ``BackgroundTaskManager.stop_task`` and collaborates with ``_tasks.get``,
        ``ValueError``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"No task found with ID: {task_id}")
        return task

    async def _start_process(self, task_id: str) -> asyncio.subprocess.Process:
        """Start process for the enclosing subsystem.

        Integration: Called by ``BackgroundTaskManager.create_shell_task``,
        ``BackgroundTaskManager._restart_agent_task`` and collaborates with ``_require_task``,
        ``asyncio.create_task``, ``ValueError``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve argv boundaries, timeouts, and child cleanup; preserve exception
        and fallback behavior expected by callers.
        """
        task = self._require_task(task_id)
        if task.command is None and task.argv is None:
            raise ValueError(f"Task {task_id} does not have a command or argv to run")

        generation = self._generations.get(task_id, 0) + 1
        self._generations[task_id] = generation
        # Merge task-specific env vars on top of the parent process environment
        # so the child sees both. Passing ``None`` lets the OS inherit env
        # directly, which is the legacy behaviour for plain shell tasks.
        merged_env: dict[str, str] | None
        if task.env:
            merged_env = {**os.environ, **task.env}
        else:
            merged_env = None

        if task.argv is not None:
            # Direct-exec route. No shell. Used for teammate spawn so we
            # don't have to round-trip Windows paths through Git Bash, which
            # cannot reliably exec ``C:\\...\\python.exe`` when launched
            # itself via ``asyncio.create_subprocess_exec`` (see #230).
            process = await asyncio.create_subprocess_exec(
                *task.argv,
                cwd=str(Path(task.cwd).resolve()),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=merged_env,
            )
        else:
            assert task.command is not None
            process = await create_shell_subprocess(
                task.command,
                cwd=task.cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=merged_env,
            )
        self._processes[task_id] = process
        self._waiters[task_id] = asyncio.create_task(
            self._watch_process(task_id, process, generation)
        )
        return process

    async def _ensure_writable_process(
        self,
        task: TaskRecord,
    ) -> asyncio.subprocess.Process:
        """Ensure writable process for the enclosing subsystem.

        Integration: Called by ``BackgroundTaskManager.write_to_task`` and collaborates with
        ``_processes.get``, ``ValueError``, ``_restart_agent_task``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        process = self._processes.get(task.id)
        if process is not None and process.stdin is not None and process.returncode is None:
            return process
        if task.type not in {"local_agent", "remote_agent", "in_process_teammate"}:
            raise ValueError(f"Task {task.id} does not accept input")
        return await self._restart_agent_task(task)

    async def _restart_agent_task(self, task: TaskRecord) -> asyncio.subprocess.Process:
        """Run the restart agent task workflow through its asynchronous collaborators.

        Integration: Called by ``BackgroundTaskManager.write_to_task``,
        ``BackgroundTaskManager._ensure_writable_process`` and collaborates with
        ``_waiters.get``, ``time.time``, ``ValueError``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
        exception and fallback behavior expected by callers.
        """
        if task.command is None and task.argv is None:
            raise ValueError(f"Task {task.id} does not have a restart command or argv")

        waiter = self._waiters.get(task.id)
        if waiter is not None and not waiter.done():
            await waiter

        restart_count = int(task.metadata.get("restart_count", "0")) + 1
        task.metadata["restart_count"] = str(restart_count)
        task.metadata["status_note"] = "Task restarted; prior interactive context was not preserved."
        task.status = "running"
        task.started_at = time.time()
        task.ended_at = None
        task.return_code = None
        with task.output_file.open("ab") as handle:
            handle.write(_TASK_RESTART_NOTICE.encode("utf-8"))
        return await self._start_process(task.id)

    async def _notify_completion_listeners(self, task: TaskRecord) -> None:
        """Run the notify completion listeners workflow through its asynchronous collaborators.

        Integration: Called by ``BackgroundTaskManager.stop_task``,
        ``BackgroundTaskManager._watch_process`` and collaborates with ``replace``,
        ``_completion_listeners.items``, ``listener``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract; preserve
        exception and fallback behavior expected by callers.
        """
        snapshot = replace(task, metadata=dict(task.metadata))
        for listener_id, listener in list(self._completion_listeners.items()):
            try:
                maybe_awaitable = listener(snapshot)
                if maybe_awaitable is not None:
                    await maybe_awaitable
            except Exception:
                log.exception("Task completion listener %s failed for task %s", listener_id, task.id)

    def close(self) -> None:
        """Best-effort cleanup for any tracked subprocesses and watcher tasks.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_waiters.clear``, ``_processes.clear``, ``_waiters.values``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        for waiter in list(self._waiters.values()):
            waiter.cancel()
        self._waiters.clear()

        for process in list(self._processes.values()):
            stdin = process.stdin
            if stdin is not None and not stdin.is_closing():
                try:
                    stdin.close()
                except RuntimeError:
                    pass
            if process.returncode is None:
                try:
                    process.kill()
                except (ProcessLookupError, RuntimeError):
                    pass
        self._processes.clear()

    async def aclose(self) -> None:
        """Asynchronously shut down tracked subprocesses and waiters.

        Integration: Called by ``DingTalkChannel.stop``, ``DiscordChannel.stop`` and
        collaborates with ``_processes.clear``, ``_waiters.clear``, ``_processes.values``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        processes = list(self._processes.values())
        waiters = list(self._waiters.values())

        for process in processes:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await _close_process_stdin(process)

        for process in processes:
            if process.returncode is None:
                try:
                    await process.wait()
                except ProcessLookupError:
                    pass

        if waiters:
            await asyncio.gather(*waiters, return_exceptions=True)

        self._processes.clear()
        self._waiters.clear()


_DEFAULT_MANAGER: BackgroundTaskManager | None = None
_DEFAULT_MANAGER_KEY: str | None = None


def get_task_manager() -> BackgroundTaskManager:
    """Return the singleton task manager.

    Integration: Called by ``create_default_command_registry``,
    ``create_default_command_registry._stats_handler`` and collaborates with ``resolve``,
    ``BackgroundTaskManager``, ``_DEFAULT_MANAGER.close``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    global _DEFAULT_MANAGER, _DEFAULT_MANAGER_KEY
    current_key = str(get_tasks_dir().resolve())
    if _DEFAULT_MANAGER is None or _DEFAULT_MANAGER_KEY != current_key:
        if _DEFAULT_MANAGER is not None:
            _DEFAULT_MANAGER.close()
        _DEFAULT_MANAGER = BackgroundTaskManager()
        _DEFAULT_MANAGER_KEY = current_key
    return _DEFAULT_MANAGER


def reset_task_manager() -> None:
    """Reset the singleton task manager, closing tracked subprocesses first.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``_DEFAULT_MANAGER.close``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    global _DEFAULT_MANAGER, _DEFAULT_MANAGER_KEY
    if _DEFAULT_MANAGER is not None:
        _DEFAULT_MANAGER.close()
    _DEFAULT_MANAGER = None
    _DEFAULT_MANAGER_KEY = None


async def shutdown_task_manager() -> None:
    """Async reset that fully reaps tracked subprocesses before clearing state.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``_DEFAULT_MANAGER.aclose``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    global _DEFAULT_MANAGER, _DEFAULT_MANAGER_KEY
    if _DEFAULT_MANAGER is not None:
        await _DEFAULT_MANAGER.aclose()
    _DEFAULT_MANAGER = None
    _DEFAULT_MANAGER_KEY = None


def _task_id(task_type: TaskType) -> str:
    """Derive task identifier from the current inputs and subsystem state.

    Integration: Called by ``BackgroundTaskManager.create_shell_task`` and collaborates with
    ``uuid4``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    prefixes = {
        "local_bash": "b",
        "local_agent": "a",
        "remote_agent": "r",
        "in_process_teammate": "t",
        "dream": "d",
    }
    return f"{prefixes[task_type]}{uuid4().hex[:8]}"


async def _close_process_stdin(process: asyncio.subprocess.Process) -> None:
    """Close process stdin for the enclosing subsystem.

    Integration: Called by ``BackgroundTaskManager.stop_task``,
    ``BackgroundTaskManager._watch_process`` and collaborates with ``stdin.close``,
    ``stdin.is_closing``, ``stdin.wait_closed``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    stdin = process.stdin
    if stdin is None or stdin.is_closing():
        return
    stdin.close()
    try:
        await stdin.wait_closed()
    except (BrokenPipeError, ConnectionResetError):
        pass
