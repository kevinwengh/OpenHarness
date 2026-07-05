"""JSON-lines backend host for the React terminal frontend.

Integration: This module participates in runtime composition and adapters for CLI, React,
Textual, headless, and ohmo callers.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve startup/readiness, protocol ordering, callback ownership, interruption,
persistence, and resource cleanup.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Coroutine
from uuid import uuid4

from openharness.api.client import SupportsStreamingMessages
from openharness.auth.manager import AuthManager
from openharness.commands import MemoryCommandBackend
from openharness.config.settings import CLAUDE_MODEL_ALIAS_OPTIONS, resolve_model_setting
from openharness.bridge import get_bridge_manager
from openharness.coordinator.coordinator_mode import is_coordinator_mode
from openharness.engine.messages import ConversationMessage, ImageBlock, TextBlock
from openharness.themes import list_themes
from openharness.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CompactProgressEvent,
    ErrorEvent,
    StatusEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from openharness.output_styles import load_output_styles
from openharness.tasks import get_task_manager
from openharness.ui.coordinator_drain import drain_coordinator_async_agents
from openharness.ui.protocol import BackendEvent, FrontendImageAttachment, FrontendRequest, TranscriptItem
from openharness.ui.runtime import build_runtime, close_runtime, handle_line, start_runtime
from openharness.services.session_backend import SessionBackend

log = logging.getLogger(__name__)

log = logging.getLogger(__name__)

_PROTOCOL_PREFIX = "OHJSON:"

RequestSource = Callable[[], Awaitable[FrontendRequest | None]]
EventSink = Callable[[BackendEvent], Awaitable[None]]


@dataclass(frozen=True)
class BackendHostConfig:
    """Capture serializable/runtime-injected inputs for one backend host session.

    ``run_backend_host`` normalizes CLI and ohmo overrides into this immutable
    value before ``ReactBackendHost`` enters its event loop. New fields must be
    forwarded into ``build_runtime`` without exposing secrets in protocol events.
    """

    model: str | None = None
    max_turns: int | None = None
    effort: str | None = None
    base_url: str | None = None
    system_prompt: str | None = None
    api_key: str | None = None
    api_format: str | None = None
    active_profile: str | None = None
    api_client: SupportsStreamingMessages | None = None
    cwd: str | None = None
    restore_messages: list[dict] | None = None
    restore_tool_metadata: dict[str, object] | None = None
    enforce_max_turns: bool = True
    permission_mode: str | None = None
    session_backend: SessionBackend | None = None
    extra_skill_dirs: tuple[str, ...] = ()
    extra_plugin_roots: tuple[str, ...] = ()
    memory_backend: MemoryCommandBackend | None = None
    include_project_memory: bool = True


class ReactBackendHost:
    """Drive one OpenHarness runtime over a structured frontend transport.

    The host owns request serialization, modal futures, active-turn cancellation,
    and runtime cleanup. Stdin/stdout remains the default terminal adapter; web
    callers may inject typed request and event callbacks without duplicating the
    runtime lifecycle. One instance belongs to one asyncio event loop and one
    controlling frontend; preserve that ownership when changing callbacks.
    """

    def __init__(
        self,
        config: BackendHostConfig,
        *,
        request_source: RequestSource | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        """Initialize loop-bound coordination state without starting resources.

        Locks, queues, futures, and active tasks are used only after ``run`` starts
        on the owning event loop. Keep modal maps keyed by protocol request ID and
        avoid creating background work in the constructor.

        Integration: Used as an internal helper or callback at this module boundary and
        collaborates with ``asyncio.Lock``, ``asyncio.Queue``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers; retain lock scope and release behavior.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._config = config
        self._request_source = request_source
        self._event_sink = event_sink
        self._bundle = None
        self._write_lock = asyncio.Lock()
        self._request_queue: asyncio.Queue[FrontendRequest] = asyncio.Queue(maxsize=128)
        self._permission_requests: dict[str, asyncio.Future[bool]] = {}
        self._edit_approval_requests: dict[str, asyncio.Future[str]] = {}
        self._question_requests: dict[str, asyncio.Future[str]] = {}
        self._permission_lock = asyncio.Lock()
        self._busy = False
        self._running = True
        self._active_request_task: asyncio.Task[bool] | None = None
        # Track last tool input per name for rich event emission
        self._last_tool_inputs: dict[str, dict] = {}
        self._edit_always_approved = False

    async def run(self) -> int:
        """Build the runtime, serve frontend requests, and close all resources.

        Startup emits ``ready`` only after runtime initialization. The main loop
        enforces one active line while the reader resolves modal responses and
        interrupts concurrently. Reader cancellation and ``close_runtime`` in
        ``finally`` are lifecycle invariants; every terminal path must retain them.
        """
        self._bundle = await build_runtime(
            model=self._config.model,
            max_turns=self._config.max_turns,
            effort=self._config.effort,
            base_url=self._config.base_url,
            system_prompt=self._config.system_prompt,
            api_key=self._config.api_key,
            api_format=self._config.api_format,
            active_profile=self._config.active_profile,
            api_client=self._config.api_client,
            cwd=self._config.cwd,
            restore_messages=self._config.restore_messages,
            restore_tool_metadata=self._config.restore_tool_metadata,
            permission_prompt=self._ask_permission,
            ask_user_prompt=self._ask_question,
            edit_approval_prompt=self._ask_edit_approval,
            enforce_max_turns=self._config.enforce_max_turns,
            permission_mode=self._config.permission_mode,
            session_backend=self._config.session_backend,
            extra_skill_dirs=self._config.extra_skill_dirs,
            extra_plugin_roots=self._config.extra_plugin_roots,
            memory_backend=self._config.memory_backend,
            include_project_memory=self._config.include_project_memory,
        )
        await start_runtime(self._bundle)
        await self._emit(
            BackendEvent.ready(
                self._bundle.app_state.get(),
                get_task_manager().list_tasks(),
                [f"/{command.name}" for command in self._bundle.commands.list_commands()],
            )
        )
        await self._emit(self._status_snapshot())

        reader = asyncio.create_task(self._read_requests())
        try:
            while self._running:
                request = await self._request_queue.get()
                if request.type == "shutdown":
                    await self._emit(BackendEvent(type="shutdown"))
                    break
                if request.type == "interrupt":
                    await self._interrupt_active_request()
                    continue
                if request.type in ("permission_response", "question_response"):
                    continue
                if request.type == "list_sessions":
                    await self._handle_list_sessions()
                    continue
                if request.type == "select_command":
                    await self._handle_select_command(request.command or "")
                    continue
                if request.type == "apply_select_command":
                    if self._busy:
                        await self._emit(BackendEvent(type="error", message="Session is busy"))
                        continue
                    self._busy = True
                    try:
                        should_continue = await self._run_active_request(
                            self._apply_select_command(
                                request.command or "",
                                request.value or "",
                            )
                        )
                    finally:
                        self._busy = False
                    if not should_continue:
                        await self._emit(BackendEvent(type="shutdown"))
                        break
                    continue
                if request.type != "submit_line":
                    await self._emit(BackendEvent(type="error", message=f"Unknown request type: {request.type}"))
                    continue
                if self._busy:
                    await self._emit(BackendEvent(type="error", message="Session is busy"))
                    continue
                line = (request.line or "").strip()
                if not line and not request.images:
                    continue
                self._busy = True
                try:
                    should_continue = await self._run_active_request(
                        self._process_line(line, images=request.images)
                    )
                finally:
                    self._busy = False
                if not should_continue:
                    await self._emit(BackendEvent(type="shutdown"))
                    break
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
            if self._bundle is not None:
                await close_runtime(self._bundle)
        return 0

    async def _read_requests(self) -> None:
        """Read typed transport requests while resolving modal replies immediately.

        The default adapter validates stdin JSON without blocking the event loop;
        an injected source supplies already-validated requests for transports such
        as WebSocket. Modal responses bypass the main queue so they cannot deadlock
        behind the turn that requested them. Transport closure fails all open
        prompts closed, interrupts the active turn, and queues shutdown.

        Integration: Called by ``ReactBackendHost.run`` and collaborates with ``strip``,
        ``asyncio.to_thread``, ``FrontendRequest.model_validate_json``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        while True:
            if self._request_source is not None:
                try:
                    request = await self._request_source()
                except Exception as exc:
                    await self._emit(BackendEvent(type="error", message=f"Invalid request: {exc}"))
                    continue
                if request is None:
                    await self._handle_transport_closed()
                    return
            else:
                raw = await asyncio.to_thread(sys.stdin.buffer.readline)
                if not raw:
                    await self._handle_transport_closed()
                    return
                payload = raw.decode("utf-8").strip()
                if not payload:
                    continue
                try:
                    request = FrontendRequest.model_validate_json(payload)
                except Exception as exc:  # pragma: no cover - defensive protocol handling
                    await self._emit(BackendEvent(type="error", message=f"Invalid request: {exc}"))
                    continue
            await self._dispatch_request(request)

    async def _dispatch_request(self, request: FrontendRequest) -> None:
        """Resolve a correlated modal reply or serialize a normal request."""

        if request.type == "permission_response" and request.request_id in self._edit_approval_requests:
            future = self._edit_approval_requests[request.request_id]
            if not future.done():
                future.set_result(_edit_approval_reply_from_request(request))
            return
        if request.type == "permission_response" and request.request_id in self._permission_requests:
            future = self._permission_requests[request.request_id]
            if not future.done():
                future.set_result(bool(request.allowed))
            return
        if request.type == "question_response" and request.request_id in self._question_requests:
            future = self._question_requests[request.request_id]
            if not future.done():
                future.set_result(request.answer or "")
            return
        if request.type == "interrupt":
            await self._interrupt_active_request()
            return
        await self._request_queue.put(request)

    async def _handle_transport_closed(self) -> None:
        """Fail closed on frontend loss and unblock every runtime waiter."""

        for future in self._permission_requests.values():
            if not future.done():
                future.set_result(False)
        for future in self._edit_approval_requests.values():
            if not future.done():
                future.set_result("reject")
        for future in self._question_requests.values():
            if not future.done():
                future.set_result("")
        await self._interrupt_active_request()
        await self._request_queue.put(FrontendRequest(type="shutdown"))

    async def _run_active_request(self, awaitable: Coroutine[Any, Any, bool]) -> bool:
        """Track one cancellable line/select task and normalize user interruption.

        The reader may cancel ``_active_request_task`` while the main loop awaits
        it. Cancellation emits recovery snapshots and ``line_complete`` so React
        can leave busy state; do not swallow unrelated exceptions here.

        Integration: Called by ``ReactBackendHost.run`` and collaborates with
        ``asyncio.create_task``, ``_emit``, ``BackendEvent``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        task = asyncio.create_task(awaitable)
        self._active_request_task = task
        try:
            return await task
        except asyncio.CancelledError:
            await self._emit(
                BackendEvent(
                    type="transcript_item",
                    item=TranscriptItem(role="system", text="Interrupted by user."),
                )
            )
            await self._emit(self._status_snapshot())
            await self._emit(BackendEvent.tasks_snapshot(get_task_manager().list_tasks()))
            await self._emit(BackendEvent(type="line_complete"))
            return True
        finally:
            if self._active_request_task is task:
                self._active_request_task = None

    async def _interrupt_active_request(self) -> None:
        """Request cancellation of the current line without shutting down the host.

        Cancellation is cooperative on the same event loop and completion is
        rendered by ``_run_active_request``. Keep this method idempotent for
        duplicate Escape/Ctrl-C requests.

        Integration: Called by ``ReactBackendHost.run``, ``ReactBackendHost._read_requests`` and
        collaborates with ``task.cancel``, ``task.done``.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        task = self._active_request_task
        if task is None or task.done():
            return
        task.cancel()

    async def _process_line(
        self,
        line: str,
        *,
        transcript_line: str | None = None,
        images: list[FrontendImageAttachment] | None = None,
    ) -> bool:
        """Submit one line to the shared runtime and translate all stream events.

        This is the Python/React turn boundary: it emits the user row, adapts
        runtime callbacks, optionally drains coordinator agents, refreshes
        authoritative state/tasks, and emits exactly one final ``line_complete``.
        Event ordering controls frontend busy state, so tool, assistant,
        compaction, error, and completion changes require both protocol suites.

        Integration: Used as an internal helper or callback at this module boundary and
        collaborates with ``_build_user_message_with_images``, ``is_coordinator_mode``,
        ``_emit``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        assert self._bundle is not None
        user_message = _build_user_message_with_images(line, images or [])
        await self._emit(
            BackendEvent(
                type="transcript_item",
                item=TranscriptItem(
                    role="user",
                    text=transcript_line or _format_transcript_line(line, images or []),
                ),
            )
        )

        async def _print_system(message: str) -> None:
            """Translate a runtime system notice into a transcript event.

            Integration: Used as an internal helper or callback at this module boundary and
            collaborates with ``_emit``, ``BackendEvent``, ``TranscriptItem``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await self._emit(
                BackendEvent(type="transcript_item", item=TranscriptItem(role="system", text=message))
            )

        async def _render_event(event: StreamEvent) -> None:
            """Map engine stream events to ordered frontend protocol events.

            ``handle_line`` awaits this callback inline, so emitted messages keep
            provider/tool ordering. Keep work bounded on the event loop and update
            TypeScript reducers whenever a mapping or payload changes.
            """
            if isinstance(event, AssistantTextDelta):
                await self._emit(BackendEvent(type="assistant_delta", message=event.text))
                return
            if isinstance(event, CompactProgressEvent):
                await self._emit(
                    BackendEvent(
                        type="compact_progress",
                        compact_phase=event.phase,
                        compact_trigger=event.trigger,
                        attempt=event.attempt,
                        compact_checkpoint=event.checkpoint,
                        compact_metadata=event.metadata,
                        message=event.message,
                    )
                )
                return
            if isinstance(event, AssistantTurnComplete):
                await self._emit(
                    BackendEvent(
                        type="assistant_complete",
                        message=event.message.text.strip(),
                        item=TranscriptItem(role="assistant", text=event.message.text.strip()),
                    )
                )
                await self._emit(BackendEvent.tasks_snapshot(get_task_manager().list_tasks()))
                return
            if isinstance(event, ToolExecutionStarted):
                self._last_tool_inputs[event.tool_name] = event.tool_input or {}
                await self._emit(
                    BackendEvent(
                        type="tool_started",
                        tool_name=event.tool_name,
                        tool_input=event.tool_input,
                        item=TranscriptItem(
                            role="tool",
                            text=f"{event.tool_name} {json.dumps(event.tool_input, ensure_ascii=True)}",
                            tool_name=event.tool_name,
                            tool_input=event.tool_input,
                        ),
                    )
                )
                return
            if isinstance(event, ToolExecutionCompleted):
                await self._emit(
                    BackendEvent(
                        type="tool_completed",
                        tool_name=event.tool_name,
                        output=event.output,
                        is_error=event.is_error,
                        item=TranscriptItem(
                            role="tool_result",
                            text=event.output,
                            tool_name=event.tool_name,
                            is_error=event.is_error,
                        ),
                    )
                )
                await self._emit(BackendEvent.tasks_snapshot(get_task_manager().list_tasks()))
                await self._emit(self._status_snapshot())
                # Emit todo_update when TodoWrite tool runs
                if event.tool_name in ("TodoWrite", "todo_write"):
                    tool_input = self._last_tool_inputs.get(event.tool_name, {})
                    # TodoWrite input may have 'todos' list or markdown content field
                    todos = tool_input.get("todos") or tool_input.get("content") or []
                    if isinstance(todos, list) and todos:
                        lines = []
                        for item in todos:
                            if isinstance(item, dict):
                                checked = item.get("status", "") in ("done", "completed", "x", True)
                                text = item.get("content") or item.get("text") or str(item)
                                lines.append(f"- [{'x' if checked else ' '}] {text}")
                        if lines:
                            await self._emit(BackendEvent(type="todo_update", todo_markdown="\n".join(lines)))
                    else:
                        await self._emit_todo_update_from_output(event.output)
                # Emit plan_mode_change when plan-related tools complete
                if event.tool_name in ("set_permission_mode", "plan_mode"):
                    assert self._bundle is not None
                    new_mode = self._bundle.app_state.get().permission_mode
                    await self._emit(BackendEvent(type="plan_mode_change", plan_mode=new_mode))
                return
            if isinstance(event, ErrorEvent):
                await self._emit(BackendEvent(type="error", message=event.message))
                await self._emit(
                    BackendEvent(type="transcript_item", item=TranscriptItem(role="system", text=event.message))
                )
                return
            if isinstance(event, StatusEvent):
                await self._emit(
                    BackendEvent(type="transcript_item", item=TranscriptItem(role="system", text=event.message))
                )
                return

        async def _clear_output() -> None:
            """Translate the shared clear-output callback into a transcript reset.

            Integration: Used as an internal helper or callback at this module boundary and
            collaborates with ``_emit``, ``BackendEvent``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await self._emit(BackendEvent(type="clear_transcript"))

        handle_line_kwargs: dict[str, Any] = {
            "print_system": _print_system,
            "render_event": _render_event,
            "clear_output": _clear_output,
        }
        if user_message is not None:
            handle_line_kwargs["user_message"] = user_message
        should_continue = await handle_line(self._bundle, line, **handle_line_kwargs)
        if is_coordinator_mode():
            await drain_coordinator_async_agents(
                self._bundle,
                prompt_seed=line,
                print_system=_print_system,
                render_event=_render_event,
            )
        await self._emit(self._status_snapshot())
        await self._emit(BackendEvent.tasks_snapshot(get_task_manager().list_tasks()))
        await self._emit(BackendEvent(type="line_complete"))
        return should_continue

    async def _apply_select_command(self, command_name: str, value: str) -> bool:
        """Convert a frontend selector choice into the canonical slash-command path.

        Selection remains presentation-only; ``handle_line`` must execute the
        resulting command so settings, persistence, and runtime refresh behavior
        stay shared with typed input.

        Integration: Called by ``ReactBackendHost.run`` and collaborates with ``lower``,
        ``value.strip``, ``_build_select_command_line``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        command = command_name.strip().lstrip("/").lower()
        selected = value.strip()
        line = self._build_select_command_line(command, selected)
        if line is None:
            await self._emit(BackendEvent(type="error", message=f"Unknown select command: {command_name}"))
            await self._emit(BackendEvent(type="line_complete"))
            return True
        return await self._process_line(line, transcript_line=f"/{command}")

    def _build_select_command_line(self, command: str, value: str) -> str | None:
        """Build a validated slash-command line for a supported selector.

        Keep this allowlist synchronized with ``_handle_select_command`` and the
        frontend command picker. Returning ``None`` prevents arbitrary command
        construction from protocol values.

        Integration: Called by ``ReactBackendHost._apply_select_command``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if command == "provider":
            return f"/provider {value}"
        if command == "resume":
            return f"/resume {value}" if value else "/resume"
        if command == "permissions":
            return f"/permissions {value}"
        if command == "theme":
            return f"/theme {value}"
        if command == "output-style":
            return f"/output-style {value}"
        if command == "effort":
            return f"/effort {value}"
        if command == "passes":
            return f"/passes {value}"
        if command == "turns":
            return f"/turns {value}"
        if command == "fast":
            return f"/fast {value}"
        if command == "vim":
            return f"/vim {value}"
        if command == "voice":
            return f"/voice {value}"
        if command == "model":
            return f"/model {value}"
        return None

    def _status_snapshot(self) -> BackendEvent:
        """Project current runtime, MCP, and bridge state into one UI event.

        The host calls this after startup, tools, interruption, and line completion.
        Keep conversion synchronous and side-effect-free because it runs inline on
        the protocol event loop.
        """
        assert self._bundle is not None
        return BackendEvent.status_snapshot(
            state=self._bundle.app_state.get(),
            mcp_servers=self._bundle.mcp_manager.list_statuses(),
            bridge_sessions=get_bridge_manager().list_sessions(),
        )

    async def _emit_todo_update_from_output(self, output: str) -> None:
        """Extract echoed checklist lines and emit a frontend todo update.

        This compatibility fallback runs after a todo tool result when structured
        input was unavailable. Keep parsing conservative so arbitrary tool output
        is not misrepresented as authoritative task state.

        Integration: Called by ``ReactBackendHost._process_line``,
        ``ReactBackendHost._process_line._render_event`` and collaborates with
        ``output.splitlines``, ``join``, ``startswith``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        # TodoWrite tools typically echo back the written content
        # We look for markdown checklist patterns in the output
        lines = output.splitlines()
        checklist_lines = [line for line in lines if line.strip().startswith("- [")]
        if checklist_lines:
            markdown = "\n".join(checklist_lines)
            await self._emit(BackendEvent(type="todo_update", todo_markdown=markdown))

    def _emit_swarm_status(self, teammates: list[dict], notifications: list[dict] | None = None) -> None:
        """Schedule a swarm-status event from a synchronous observer callback.

        Swarm integrations cannot await the protocol writer directly, so this
        method creates a task on the host's current event loop. Call it only while
        the host loop is running; ordering and task-error handling need review if
        swarm callbacks become cross-thread or survive shutdown.

        Integration: Used as an internal helper or callback at this module boundary and
        collaborates with ``asyncio.get_event_loop``, ``loop.create_task``, ``_emit``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        loop.create_task(
            self._emit(BackendEvent(type="swarm_status", swarm_teammates=teammates, swarm_notifications=notifications))
        )

    async def _handle_list_sessions(self) -> None:
        """Load recent backend snapshots and emit resume-selector options.

        The session backend owns ordering and persistence. This adapter performs
        bounded synchronous listing on the event loop and emits presentation-only
        labels; offload it if a future backend can block on remote I/O.

        Integration: Called by ``ReactBackendHost.run``,
        ``ReactBackendHost._handle_select_command`` and collaborates with
        ``_bundle.session_backend.list_snapshots``, ``_time.strftime``, ``options.append``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        import time as _time

        assert self._bundle is not None
        sessions = self._bundle.session_backend.list_snapshots(self._bundle.cwd, limit=10)
        options = []
        for s in sessions:
            ts = _time.strftime("%m/%d %H:%M", _time.localtime(s["created_at"]))
            summary = s.get("summary", "")[:50] or "(no summary)"
            options.append({
                "value": s["session_id"],
                "label": f"{ts}  {s['message_count']}msg  {summary}",
            })
        await self._emit(
            BackendEvent(
                type="select_request",
                modal={"kind": "select", "title": "Resume Session", "command": "resume"},
                select_options=options,
            )
        )

    async def _handle_select_command(self, command_name: str) -> None:
        """Build and emit options for frontend-interactive slash commands.

        Values come from authoritative settings, app state, auth profiles, and
        registries, while application still flows through ``_apply_select_command``.
        Keep branches aligned with command handlers and TypeScript selectors; avoid
        secret-bearing descriptions and blocking external work on the event loop.
        """
        assert self._bundle is not None
        command = command_name.strip().lstrip("/").lower()
        if command == "resume":
            await self._handle_list_sessions()
            return

        settings = self._bundle.current_settings()
        state = self._bundle.app_state.get()
        _, active_profile = settings.resolve_profile()
        current_model = settings.model

        if command == "provider":
            statuses = AuthManager(settings).get_profile_statuses()
            options = [
                {
                    "value": name,
                    "label": info["label"],
                    "description": f"{info['provider']} / {info['auth_source']}" + (" [missing auth]" if not info["configured"] else ""),
                    "active": info["active"],
                }
                for name, info in statuses.items()
            ]
            await self._emit(
                BackendEvent(
                    type="select_request",
                    modal={"kind": "select", "title": "Provider Profile", "command": "provider"},
                    select_options=options,
                )
            )
            return

        if command == "permissions":
            options = [
                {
                    "value": "default",
                    "label": "Default",
                    "description": "Ask before write/execute operations",
                    "active": settings.permission.mode.value == "default",
                },
                {
                    "value": "full_auto",
                    "label": "Auto",
                    "description": "Allow all tools automatically",
                    "active": settings.permission.mode.value == "full_auto",
                },
                {
                    "value": "plan",
                    "label": "Plan Mode",
                    "description": "Block all write operations",
                    "active": settings.permission.mode.value == "plan",
                },
            ]
            await self._emit(
                BackendEvent(
                    type="select_request",
                    modal={"kind": "select", "title": "Permission Mode", "command": "permissions"},
                    select_options=options,
                )
            )
            return

        if command == "theme":
            options = [
                {
                    "value": name,
                    "label": name,
                    "active": name == settings.theme,
                }
                for name in list_themes()
            ]
            await self._emit(
                BackendEvent(
                    type="select_request",
                    modal={"kind": "select", "title": "Theme", "command": "theme"},
                    select_options=options,
                )
            )
            return

        if command == "output-style":
            options = [
                {
                    "value": style.name,
                    "label": style.name,
                    "description": style.source,
                    "active": style.name == settings.output_style,
                }
                for style in load_output_styles()
            ]
            await self._emit(
                BackendEvent(
                    type="select_request",
                    modal={"kind": "select", "title": "Output Style", "command": "output-style"},
                    select_options=options,
                )
            )
            return

        if command == "effort":
            options = [
                {"value": "low", "label": "Low", "description": "Fastest responses", "active": settings.effort == "low"},
                {"value": "medium", "label": "Medium", "description": "Balanced reasoning", "active": settings.effort == "medium"},
                {"value": "high", "label": "High", "description": "Deepest reasoning", "active": settings.effort == "high"},
                {"value": "xhigh", "label": "XHigh", "description": "Extra high reasoning", "active": settings.effort == "xhigh"},
            ]
            await self._emit(
                BackendEvent(
                    type="select_request",
                    modal={"kind": "select", "title": "Reasoning Effort", "command": "effort"},
                    select_options=options,
                )
            )
            return

        if command == "passes":
            current = int(state.passes or settings.passes)
            options = [
                {"value": str(value), "label": f"{value} pass{'es' if value != 1 else ''}", "active": value == current}
                for value in range(1, 9)
            ]
            await self._emit(
                BackendEvent(
                    type="select_request",
                    modal={"kind": "select", "title": "Reasoning Passes", "command": "passes"},
                    select_options=options,
                )
            )
            return

        if command == "turns":
            current = self._bundle.engine.max_turns
            values = {32, 64, 128, 200, 256, 512}
            if isinstance(current, int):
                values.add(current)
            options = [{"value": "unlimited", "label": "Unlimited", "description": "Do not hard-stop this session", "active": current is None}]
            options.extend(
                {"value": str(value), "label": f"{value} turns", "active": value == current}
                for value in sorted(values)
            )
            await self._emit(
                BackendEvent(
                    type="select_request",
                    modal={"kind": "select", "title": "Max Turns", "command": "turns"},
                    select_options=options,
                )
            )
            return

        if command == "fast":
            current = bool(state.fast_mode)
            options = [
                {"value": "on", "label": "On", "description": "Prefer shorter, faster responses", "active": current},
                {"value": "off", "label": "Off", "description": "Use normal response mode", "active": not current},
            ]
            await self._emit(
                BackendEvent(
                    type="select_request",
                    modal={"kind": "select", "title": "Fast Mode", "command": "fast"},
                    select_options=options,
                )
            )
            return

        if command == "vim":
            current = bool(state.vim_enabled)
            options = [
                {"value": "on", "label": "On", "description": "Enable Vim keybindings", "active": current},
                {"value": "off", "label": "Off", "description": "Use standard keybindings", "active": not current},
            ]
            await self._emit(
                BackendEvent(
                    type="select_request",
                    modal={"kind": "select", "title": "Vim Mode", "command": "vim"},
                    select_options=options,
                )
            )
            return

        if command == "voice":
            current = bool(state.voice_enabled)
            options = [
                {"value": "on", "label": "On", "description": state.voice_reason or "Enable voice mode", "active": current},
                {"value": "off", "label": "Off", "description": "Disable voice mode", "active": not current},
            ]
            await self._emit(
                BackendEvent(
                    type="select_request",
                    modal={"kind": "select", "title": "Voice Mode", "command": "voice"},
                    select_options=options,
                )
            )
            return

        if command == "model":
            options = self._model_select_options(current_model, active_profile.provider, active_profile.allowed_models)
            await self._emit(
                BackendEvent(
                    type="select_request",
                    modal={"kind": "select", "title": "Model", "command": "model"},
                    select_options=options,
                )
            )
            return

        await self._emit(BackendEvent(type="error", message=f"No selector available for /{command}"))

    def _model_select_options(self, current_model: str, provider: str, allowed_models: list[str] | None = None) -> list[dict[str, object]]:
        """Return bounded model choices using profile restrictions before heuristics.

        This is setup UX, not provider capability enforcement. Preserve explicit
        ``allowed_models`` precedence and alias-aware active selection; provider
        additions must be synchronized with profile/model resolution tests.

        Integration: Called by ``ReactBackendHost._handle_select_command`` and collaborates with
        ``provider.lower``, ``resolve_model_setting``, ``families.extend``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if allowed_models:
            return [
                {
                    "value": value,
                    "label": value,
                    "description": "Allowed for this profile",
                    "active": value == current_model,
                }
                for value in allowed_models
            ]
        provider_name = provider.lower()
        if provider_name in {"anthropic", "anthropic_claude"}:
            resolved_current = resolve_model_setting(current_model, provider_name)
            return [
                {
                    "value": value,
                    "label": label,
                    "description": description,
                    "active": value == current_model
                    or resolve_model_setting(value, provider_name) == resolved_current,
                }
                for value, label, description in CLAUDE_MODEL_ALIAS_OPTIONS
            ]
        families: list[tuple[str, str]] = []
        if provider_name in {"openai-codex", "openai", "openai-compatible", "openrouter", "github_copilot"}:
            families.extend(
                [
                    ("gpt-5.4", "OpenAI flagship"),
                    ("gpt-5", "General GPT-5"),
                    ("gpt-4.1", "Stable GPT-4.1"),
                    ("o4-mini", "Fast reasoning"),
                ]
            )
        elif provider_name in {"moonshot", "moonshot-compatible"}:
            families.extend(
                [
                    ("kimi-k2.5", "Moonshot K2.5"),
                    ("kimi-k2-turbo-preview", "Faster Moonshot"),
                ]
            )
        elif provider_name == "dashscope":
            families.extend(
                [
                    ("qwen3.5-flash", "Fast Qwen"),
                    ("qwen3-max", "Strong Qwen"),
                    ("deepseek-r1", "Reasoning model"),
                ]
            )
        elif provider_name == "gemini":
            families.extend(
                [
                    ("gemini-2.5-pro", "Gemini Pro"),
                    ("gemini-2.5-flash", "Gemini Flash"),
                ]
            )
        elif provider_name == "minimax":
            families.extend(
                [
                    ("MiniMax-M2.7", "MiniMax flagship"),
                    ("MiniMax-M2.7-highspeed", "MiniMax fast"),
                ]
            )

        seen: set[str] = set()
        options: list[dict[str, object]] = []
        for value, description in [(current_model, "Current model"), *families]:
            if not value or value in seen:
                continue
            seen.add(value)
            options.append(
                {
                    "value": value,
                    "label": value,
                    "description": description,
                    "active": value == current_model,
                }
            )
        return options

    async def _ask_permission(self, tool_name: str, reason: str) -> bool:
        """Serialize a tool confirmation modal and await its correlated response.

        The permission lock prevents overlapping approval UIs while the request
        reader resolves this future concurrently. Timeout defaults to denial and
        cleanup removes the ID; preserve those safety and deadlock-avoidance
        properties when changing modal behavior.
        """
        async with self._permission_lock:
            request_id = uuid4().hex
            future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            self._permission_requests[request_id] = future
            await self._emit(
                BackendEvent(
                    type="modal_request",
                    modal={
                        "kind": "permission",
                        "request_id": request_id,
                        "tool_name": tool_name,
                        "reason": reason,
                    },
                )
            )
            try:
                return await asyncio.wait_for(future, timeout=300)
            except asyncio.TimeoutError:
                log.warning("Permission request %s timed out after 300s, denying", request_id)
                return False
            finally:
                self._permission_requests.pop(request_id, None)

    def _current_permission_mode(self) -> str:
        """Read the live permission mode, falling back before runtime startup.

        Edit approval uses this synchronous helper to honor mode changes made
        during the session. Keep returned values aligned with permission policy.
        """
        if self._bundle is None:
            return str(self._config.permission_mode or "")
        return str(self._bundle.app_state.get().permission_mode or "")

    async def _ask_edit_approval(self, path: str, diff: str, added: int, removed: int) -> str:
        """Show a serialized edit preview and return once/always/reject.

        Full-auto and prior session-wide approval bypass the modal. Otherwise the
        request reader resolves a correlated future with a fail-closed timeout;
        keep the diff bounded upstream and always clear modal state during cleanup.

        Integration: Used as an internal helper or callback at this module boundary and
        collaborates with ``create_future``, ``_current_permission_mode``, ``uuid4``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        if self._edit_always_approved or self._current_permission_mode() == "full_auto":
            return "always"

        async with self._permission_lock:
            request_id = uuid4().hex
            future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            self._edit_approval_requests[request_id] = future
            await self._emit(
                BackendEvent(
                    type="modal_request",
                    modal={
                        "kind": "edit_diff",
                        "request_id": request_id,
                        "path": path,
                        "diff": diff,
                        "added": added,
                        "removed": removed,
                    },
                )
            )
            try:
                reply = await asyncio.wait_for(future, timeout=300)
            except asyncio.TimeoutError:
                log.warning("Edit approval request %s timed out after 300s, denying", request_id)
                reply = "reject"
            finally:
                self._edit_approval_requests.pop(request_id, None)
                await self._emit(BackendEvent(type="modal_request", modal=None))

            if reply == "always":
                self._edit_always_approved = True
            return reply

    async def _ask_question(self, question: str) -> str:
        """Emit a runtime question modal and await the matching frontend answer.

        Unlike permission prompts this currently has no timeout, so shutdown or
        cancellation must remain able to unwind the awaiting prompt. Preserve
        request-ID cleanup and direct reader-to-future resolution.
        """
        request_id = uuid4().hex
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._question_requests[request_id] = future
        await self._emit(
            BackendEvent(
                type="modal_request",
                modal={
                    "kind": "question",
                    "request_id": request_id,
                    "question": question,
                },
            )
        )
        try:
            return await future
        finally:
            self._question_requests.pop(request_id, None)

    async def _emit(self, event: BackendEvent) -> None:
        """Write one ordered event through the injected or stdout transport.

        All producer tasks share ``_write_lock`` so event lines cannot interleave.
        Stdout is the machine protocol while stderr carries diagnostics; preserve
        the prefix, newline, UTF-8 encoding, flush, and event-loop serialization.

        Integration: Called by ``ReactBackendHost.run``, ``ReactBackendHost._read_requests`` and
        collaborates with ``log.debug``, ``sys.stdout.write``, ``sys.stdout.flush``.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        log.debug("emit event: type=%s tool=%s", event.type, getattr(event, "tool_name", None))
        async with self._write_lock:
            if self._event_sink is not None:
                await self._event_sink(event)
                return
            payload = _PROTOCOL_PREFIX + event.model_dump_json() + "\n"
            buffer = getattr(sys.stdout, "buffer", None)
            if buffer is not None:
                buffer.write(payload.encode("utf-8"))
                buffer.flush()
                return
            sys.stdout.write(payload)
            sys.stdout.flush()


def _build_user_message_with_images(
    line: str,
    images: list[FrontendImageAttachment],
) -> ConversationMessage | None:
    """Construct multimodal user content when the frontend supplied images.

    Returning ``None`` for text-only input lets ``handle_line`` retain slash-command
    parsing. For image input, preserve validated order and a non-empty text block;
    changes must remain compatible with image preprocessing and session replay.

    Integration: Called by ``ReactBackendHost._process_line`` and collaborates with
    ``content.extend``, ``ConversationMessage.from_user_content``, ``TextBlock``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking; retain lock scope and release behavior.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if not images:
        return None
    content = [TextBlock(text=line or "Please analyze the attached image.")]
    content.extend(
        ImageBlock(
            media_type=image.media_type,
            data=image.data,
            source_path=image.source_path or "",
        )
        for image in images
    )
    return ConversationMessage.from_user_content(content)


def _format_transcript_line(line: str, images: list[FrontendImageAttachment]) -> str:
    """Render a compact user-facing attachment marker without embedding image data.

    The transcript is presentation state, not the provider message. Keep base64
    payloads and local paths out of this text.

    Integration: Called by ``ReactBackendHost._process_line``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if not images:
        return line
    noun = "image" if len(images) == 1 else "images"
    attachment_line = f"[{len(images)} {noun} attached]"
    return f"{line}\n{attachment_line}" if line else attachment_line


async def run_backend_host(
    *,
    model: str | None = None,
    max_turns: int | None = None,
    effort: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_format: str | None = None,
    active_profile: str | None = None,
    cwd: str | None = None,
    api_client: SupportsStreamingMessages | None = None,
    restore_messages: list[dict] | None = None,
    restore_tool_metadata: dict[str, object] | None = None,
    enforce_max_turns: bool = True,
    permission_mode: str | None = None,
    session_backend: SessionBackend | None = None,
    extra_skill_dirs: tuple[str | Path, ...] = (),
    extra_plugin_roots: tuple[str | Path, ...] = (),
    memory_backend: MemoryCommandBackend | None = None,
    include_project_memory: bool = True,
) -> int:
    """Normalize entrypoint options and run one structured backend-host lifecycle.

    ``run_repl(--backend-only)`` and ohmo adapters enter here. Working-directory
    selection occurs before runtime composition; extra roots are resolved before
    crossing the immutable config boundary. Preserve option forwarding and await
    the host so its reader, active task, and runtime clean up on the same loop.
    """
    if cwd:
        os.chdir(cwd)
    host = ReactBackendHost(
        BackendHostConfig(
            model=model,
            max_turns=max_turns,
            effort=effort,
            base_url=base_url,
            system_prompt=system_prompt,
            api_key=api_key,
            api_format=api_format,
            active_profile=active_profile,
            api_client=api_client,
            cwd=cwd,
            restore_messages=restore_messages,
            restore_tool_metadata=restore_tool_metadata,
            enforce_max_turns=enforce_max_turns,
            permission_mode=permission_mode,
            session_backend=session_backend,
            extra_skill_dirs=tuple(str(Path(path).expanduser().resolve()) for path in extra_skill_dirs),
            extra_plugin_roots=tuple(str(Path(path).expanduser().resolve()) for path in extra_plugin_roots),
            memory_backend=memory_backend,
            include_project_memory=include_project_memory,
        )
    )
    return await host.run()


__all__ = ["run_backend_host", "ReactBackendHost", "BackendHostConfig"]


def _edit_approval_reply_from_request(request: FrontendRequest) -> str:
    """Normalize modern and legacy permission replies into edit-decision values.

    Explicit ``once``/``always``/``reject`` wins; the boolean fallback keeps older
    frontends compatible and fails closed when not allowed.

    Integration: Called by ``ReactBackendHost._read_requests`` and collaborates with ``lower``,
    ``strip``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    reply = (request.permission_reply or "").strip().lower()
    if reply in {"once", "always", "reject"}:
        return reply
    return "once" if bool(request.allowed) else "reject"
