"""Structured protocol models for the React TUI backend.

Integration: This module participates in runtime composition and adapters for CLI, React,
Textual, headless, and ohmo callers.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve startup/readiness, protocol ordering, callback ownership, interruption,
persistence, and resource cleanup.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from openharness.state.app_state import AppState
from openharness.bridge.manager import BridgeSessionRecord
from openharness.mcp.types import McpConnectionStatus
from openharness.tasks.types import TaskRecord


class FrontendImageAttachment(BaseModel):
    """Validate an image payload crossing from React into Python.

    ``useBackendSession`` serializes this shape and ``backend_host`` converts it
    into engine content blocks. Keep fields synchronized with the TypeScript
    protocol and validate before base64 data reaches prompt construction.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    media_type: str
    data: str
    source_path: str | None = None

    @field_validator("media_type")
    @classmethod
    def _validate_media_type(cls, value: str) -> str:
        """Reject non-image media types at the process protocol boundary.

        This synchronous Pydantic validator runs while the backend request reader
        parses a line; keep it deterministic and aligned with supported image
        blocks when formats change.
        """
        if not value.startswith("image/"):
            raise ValueError("image attachment media_type must start with image/")
        return value

    @field_validator("data")
    @classmethod
    def _validate_data(cls, value: str) -> str:
        """Require a non-empty encoded payload before building an image block.

        Integration: Used as an internal helper or callback at this module boundary and
        collaborates with ``field_validator``, ``value.strip``, ``ValueError``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        if not value.strip():
            raise ValueError("image attachment data is required")
        return value


class FrontendRequest(BaseModel):
    """Describe one newline-delimited request sent to the Python backend.

    The backend reader validates this discriminated-by-convention shape before
    queueing work or resolving a modal future. New request types or fields must be
    added to the TypeScript union, host dispatch, and protocol tests together.

    Integration: Constructed or referenced by ``ReactBackendHost._read_requests``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    type: Literal[
        "submit_line",
        "permission_response",
        "question_response",
        "list_sessions",
        "select_command",
        "apply_select_command",
        "interrupt",
        "shutdown",
    ]
    line: str | None = None
    command: str | None = None
    value: str | None = None
    request_id: str | None = None
    allowed: bool | None = None
    permission_reply: str | None = None
    answer: str | None = None
    images: list[FrontendImageAttachment] = Field(default_factory=list)


class TranscriptItem(BaseModel):
    """Carry one presentation-safe transcript row to the React renderer.

    This is not durable conversation state. Keep roles and optional tool fields
    aligned with frontend rendering without leaking internal message objects or
    sensitive metadata.

    Integration: Constructed or referenced by ``ReactBackendHost._run_active_request``,
    ``ReactBackendHost._process_line``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    role: Literal["system", "user", "assistant", "tool", "tool_result", "log"]
    text: str
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    is_error: bool | None = None


class TaskSnapshot(BaseModel):
    """Represent the bounded task fields exposed across the UI protocol.

    Task management retains the authoritative ``TaskRecord``; this snapshot is a
    presentation copy. Schema changes require matching TypeScript types and must
    avoid serializing live process handles or arbitrary objects.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    id: str
    type: str
    status: str
    description: str
    metadata: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_record(cls, record: TaskRecord) -> "TaskSnapshot":
        """Copy a task record into the JSON-safe frontend schema.

        Backend snapshots call this synchronously on the event loop, so conversion
        must remain side-effect-free and bounded.

        Integration: Called by ``BackendEvent.ready``, ``BackendEvent.tasks_snapshot`` and
        collaborates with ``cls``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return cls(
            id=record.id,
            type=record.type,
            status=record.status,
            description=record.description,
            metadata=dict(record.metadata),
        )


class BackendEvent(BaseModel):
    """Describe one prefixed JSON event emitted to the React frontend.

    ``ReactBackendHost`` serializes these models under ``OHJSON:`` and
    ``useBackendSession`` dispatches on ``type``. Optional fields support several
    event variants; any contract change must update both languages, preserve
    ordering semantics, and keep ``line_complete`` as the end-of-turn boundary.

    Integration: Constructed or referenced by ``ReactBackendHost.run``,
    ``ReactBackendHost._read_requests``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    type: Literal[
        "ready",
        "state_snapshot",
        "tasks_snapshot",
        "transcript_item",
        "compact_progress",
        "assistant_delta",
        "assistant_complete",
        "line_complete",
        "tool_started",
        "tool_completed",
        "clear_transcript",
        "modal_request",
        "select_request",
        "todo_update",
        "plan_mode_change",
        "swarm_status",
        "error",
        "shutdown",
    ]
    select_options: list[dict[str, Any]] | None = None
    message: str | None = None
    item: TranscriptItem | None = None
    state: dict[str, Any] | None = None
    tasks: list[TaskSnapshot] | None = None
    mcp_servers: list[dict[str, Any]] | None = None
    bridge_sessions: list[dict[str, Any]] | None = None
    commands: list[str] | None = None
    modal: dict[str, Any] | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    output: str | None = None
    is_error: bool | None = None
    compact_phase: str | None = None
    compact_trigger: str | None = None
    attempt: int | None = None
    compact_checkpoint: str | None = None
    compact_metadata: dict[str, Any] | None = None
    # New fields for enhanced events
    todo_markdown: str | None = None
    plan_mode: str | None = None
    swarm_teammates: list[dict[str, Any]] | None = None
    swarm_notifications: list[dict[str, Any]] | None = None

    @classmethod
    def ready(
        cls,
        state: AppState,
        tasks: list[TaskRecord],
        commands: list[str],
    ) -> "BackendEvent":
        """Build the initial state/task/command payload that unlocks frontend input.

        The host emits this once runtime startup completes. Keep it comprehensive
        enough for first render and free of resources that cannot be JSON encoded.

        Integration: Called by ``ReactBackendHost.run`` and collaborates with ``cls``,
        ``_state_payload``, ``TaskSnapshot.from_record``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return cls(
            type="ready",
            state=_state_payload(state),
            tasks=[TaskSnapshot.from_record(task) for task in tasks],
            mcp_servers=[],
            bridge_sessions=[],
            commands=commands,
        )

    @classmethod
    def state_snapshot(cls, state: AppState) -> "BackendEvent":
        """Build a lightweight authoritative application-state refresh.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``cls``, ``_state_payload``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return cls(type="state_snapshot", state=_state_payload(state))

    @classmethod
    def tasks_snapshot(cls, tasks: list[TaskRecord]) -> "BackendEvent":
        """Build a task-list refresh while preserving task-manager ordering.

        Integration: Called by ``ReactBackendHost._run_active_request``,
        ``ReactBackendHost._process_line`` and collaborates with ``cls``,
        ``TaskSnapshot.from_record``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return cls(
            type="tasks_snapshot",
            tasks=[TaskSnapshot.from_record(task) for task in tasks],
        )

    @classmethod
    def status_snapshot(
        cls,
        *,
        state: AppState,
        mcp_servers: list[McpConnectionStatus],
        bridge_sessions: list[BridgeSessionRecord],
    ) -> "BackendEvent":
        """Build the richer state refresh including MCP and bridge status.

        The backend emits this after line processing and relevant commands.
        Conversion is synchronous on the event loop; keep lists bounded upstream,
        JSON-safe, and synchronized with frontend status consumers.
        """
        return cls(
            type="state_snapshot",
            state=_state_payload(state),
            mcp_servers=[
                {
                    "name": server.name,
                    "state": server.state,
                    "detail": server.detail,
                    "transport": server.transport,
                    "auth_configured": server.auth_configured,
                    "tool_count": len(server.tools),
                    "resource_count": len(server.resources),
                }
                for server in mcp_servers
            ],
            bridge_sessions=[
                {
                    "session_id": session.session_id,
                    "command": session.command,
                    "cwd": session.cwd,
                    "pid": session.pid,
                    "status": session.status,
                    "started_at": session.started_at,
                    "output_path": session.output_path,
                }
                for session in bridge_sessions
            ],
        )


def _state_payload(state: AppState) -> dict[str, Any]:
    """Project authoritative runtime state into the stable frontend payload.

    This function centralizes field naming for ready and subsequent snapshots.
    Additions require TypeScript updates; do not expose credentials or mutable
    internal objects, and retain permission-mode formatting for presentation.

    Integration: Called by ``BackendEvent.ready``, ``BackendEvent.state_snapshot`` and
    collaborates with ``_format_permission_mode``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return {
        "model": state.model,
        "cwd": state.cwd,
        "provider": state.provider,
        "auth_status": state.auth_status,
        "base_url": state.base_url,
        "permission_mode": _format_permission_mode(state.permission_mode),
        "theme": state.theme,
        "vim_enabled": state.vim_enabled,
        "voice_enabled": state.voice_enabled,
        "voice_available": state.voice_available,
        "voice_reason": state.voice_reason,
        "fast_mode": state.fast_mode,
        "effort": state.effort,
        "passes": state.passes,
        "mcp_connected": state.mcp_connected,
        "mcp_failed": state.mcp_failed,
        "bridge_sessions": state.bridge_sessions,
        "output_style": state.output_style,
        "keybindings": dict(state.keybindings),
    }


_MODE_LABELS = {
    "default": "Default",
    "plan": "Plan Mode",
    "full_auto": "Auto",
    "PermissionMode.DEFAULT": "Default",
    "PermissionMode.PLAN": "Plan Mode",
    "PermissionMode.FULL_AUTO": "Auto",
}


def _format_permission_mode(raw: str) -> str:
    """Convert stored permission-mode values into frontend display labels.

    Both enum stringification and plain configuration values occur at this
    boundary. Unknown values pass through for forward compatibility; keep labels
    synchronized with frontend mode selectors.

    Integration: Called by ``_state_payload`` and collaborates with ``_MODE_LABELS.get``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return _MODE_LABELS.get(raw, raw)


__all__ = [
    "BackendEvent",
    "FrontendImageAttachment",
    "FrontendRequest",
    "TaskSnapshot",
    "TranscriptItem",
]
