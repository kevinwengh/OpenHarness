"""Tool for creating local cron-style jobs.

Integration: This module participates in model-callable tools registered with the shared engine
governance path.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve Pydantic schemas, async ToolResult behavior, read-only policy,
context.cwd, hooks, sandboxing, output bounds, and registration.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from openharness.services.cron import upsert_cron_job, validate_cron_expression, validate_timezone
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class CronCreateToolInput(BaseModel):
    """Arguments for cron job creation.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    name: str = Field(description="Unique cron job name")
    schedule: str = Field(
        description=(
            "Cron schedule expression (e.g. '*/5 * * * *' for every 5 minutes, "
            "'0 9 * * 1-5' for weekdays at 9am)"
        ),
    )
    command: str | None = Field(default=None, description="Shell command to run when triggered")
    message: str | None = Field(default=None, description="Instruction for an agent_turn cron job")
    timezone: str | None = Field(default=None, description="IANA timezone for interpreting cron schedule")
    cwd: str | None = Field(default=None, description="Optional working directory override")
    enabled: bool = Field(default=True, description="Whether the job is active")
    payload: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional nanobot-style payload. Example: "
            "{'kind': 'agent_turn', 'message': 'check GitHub', 'deliver': True, 'channel': 'feishu', 'to': 'ou_xxx'}."
        ),
    )
    notify: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional notification target. Example: "
            "{'type': 'feishu_dm', 'user_open_id': 'ou_xxx'} to send job output to a Feishu private chat."
        ),
    )


class CronCreateTool(BaseTool):
    """Create or replace a local cron job.

    Integration: Constructed or referenced by ``create_default_tool_registry``.

    Event loop: Async methods ``execute`` run on their caller's loop; instances must retain
    clear task, cancellation, and cleanup ownership.

    Change safety: Keep the input schema, read-only classification, async ``ToolResult``
    contract, permission metadata, hooks, sandbox behavior, and registration synchronized.
    """

    name = "cron_create"
    description = (
        "Create or replace a local cron job with a standard cron expression. "
        "Use 'oh cron start' to run the scheduler daemon."
    )
    input_model = CronCreateToolInput

    async def execute(
        self,
        arguments: CronCreateToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Execute one model-requested ``CronCreateTool`` invocation.

        Integration: Exposed through ``CronCreateTool`` and collaborates with
        ``upsert_cron_job``, ``ToolResult``, ``validate_cron_expression``.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block.

        Change safety: Preserve the asynchronous ``ToolResult`` contract, ``context.cwd``, and
        normalized operational failures; preserve permission, hook, sandbox, metadata, and
        output-size assumptions expected by callers.

        Tool contract: The engine validates the Pydantic input and applies hooks and permission
        policy before awaiting this method. Return ``ToolResult`` for expected operational
        failures, resolve paths from ``context.cwd``, keep output and metadata serializable and
        bounded, and do not block the event loop. Revisit sandbox routing, secret redaction,
        tool-result replay, and registration whenever execution behavior changes.
        """
        if not validate_cron_expression(arguments.schedule):
            return ToolResult(
                output=(
                    f"Invalid cron expression: {arguments.schedule!r}\n"
                    "Use standard 5-field format: minute hour day month weekday\n"
                    "Examples: '*/5 * * * *' (every 5 min), '0 9 * * 1-5' (weekdays 9am)"
                ),
                is_error=True,
            )
        if not validate_timezone(arguments.timezone):
            return ToolResult(output=f"Invalid timezone: {arguments.timezone!r}", is_error=True)

        payload = dict(arguments.payload or {})
        if arguments.message:
            payload.setdefault("kind", "agent_turn")
            payload.setdefault("message", arguments.message)
        if arguments.notify is not None:
            payload.setdefault("deliver", True)
            if str(arguments.notify.get("type") or "").strip().lower() == "feishu_dm":
                payload.setdefault("channel", "feishu")
                payload.setdefault("to", arguments.notify.get("user_open_id") or arguments.notify.get("open_id"))

        if payload and not payload.get("message") and not arguments.command:
            return ToolResult(output="Cron job requires payload.message, message, or command.", is_error=True)
        if not payload and not arguments.command:
            return ToolResult(output="Cron job requires command or message.", is_error=True)

        job = {
            "name": arguments.name,
            "schedule": arguments.schedule,
            "cwd": arguments.cwd or str(context.cwd),
            "enabled": arguments.enabled,
        }
        if arguments.timezone:
            job["timezone"] = arguments.timezone
        if arguments.command is not None:
            job["command"] = arguments.command
        if payload:
            payload.setdefault("kind", "agent_turn")
            job["payload"] = payload
        if arguments.notify is not None:
            job["notify"] = arguments.notify
        upsert_cron_job(job)
        status = "enabled" if arguments.enabled else "disabled"
        return ToolResult(
            output=f"Created cron job '{arguments.name}' [{arguments.schedule}] ({status})"
        )
