"""Tool for listing local cron jobs.

Integration: This module participates in model-callable tools registered with the shared engine
governance path.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve Pydantic schemas, async ToolResult behavior, read-only policy,
context.cwd, hooks, sandboxing, output bounds, and registration.
"""

from __future__ import annotations

from pydantic import BaseModel

from openharness.services.cron import load_cron_jobs
from openharness.services.cron_scheduler import is_scheduler_running
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class CronListToolInput(BaseModel):
    """Arguments for cron listing.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """


class CronListTool(BaseTool):
    """List local cron jobs.

    Integration: Constructed or referenced by ``create_default_tool_registry``.

    Event loop: Async methods ``execute`` run on their caller's loop; instances must retain
    clear task, cancellation, and cleanup ownership.

    Change safety: Keep the input schema, read-only classification, async ``ToolResult``
    contract, permission metadata, hooks, sandbox behavior, and registration synchronized.
    """

    name = "cron_list"
    description = "List configured local cron jobs with schedule, status, and next run time."
    input_model = CronListToolInput

    def is_read_only(self, arguments: CronListToolInput) -> bool:
        """Classify whether this ``CronListTool`` invocation can mutate state.

        Integration: Exposed through ``CronListTool``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve conservative argument-aware classification used by permission
        policy expected by callers.

        Tool contract: Permission policy trusts this argument-aware classification before
        execution. Return ``True`` only when the invocation cannot mutate local files,
        processes, remote services, configuration, or shared runtime state; prefer a
        conservative ``False`` when uncertain.
        """
        del arguments
        return True

    async def execute(
        self,
        arguments: CronListToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Execute one model-requested ``CronListTool`` invocation.

        Integration: Exposed through ``CronListTool`` and collaborates with ``load_cron_jobs``,
        ``ToolResult``, ``is_scheduler_running``.

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
        del arguments, context
        jobs = load_cron_jobs()
        if not jobs:
            return ToolResult(output="No cron jobs configured.")

        scheduler = "running" if is_scheduler_running() else "stopped"
        lines = [f"Scheduler: {scheduler}", ""]

        for job in jobs:
            enabled = "on" if job.get("enabled", True) else "off"
            last_run = job.get("last_run", "never")
            if last_run != "never":
                last_run = last_run[:19]
            next_run = job.get("next_run", "n/a")
            if next_run != "n/a":
                next_run = next_run[:19]
            last_status = job.get("last_status", "")
            status_str = f" ({last_status})" if last_status else ""
            notify = job.get("notify")
            notify_line = ""
            if isinstance(notify, dict):
                notify_type = notify.get("type", "?")
                target = notify.get("user_open_id") or notify.get("open_id") or notify.get("chat_id") or "?"
                notify_line = f"\n     notify: {notify_type} -> {target}"
            timezone = f" ({job['timezone']})" if job.get("timezone") else ""
            payload = job.get("payload")
            payload_line = ""
            if isinstance(payload, dict):
                payload_line = f"\n     payload: {payload.get('kind', 'agent_turn')} -> {payload.get('channel', '?')}:{payload.get('to', '?')}"
            command = job.get("command") or "(agent_turn)"
            lines.append(
                f"[{enabled}] {job['name']}  {job.get('schedule', '?')}{timezone}\n"
                f"     cmd: {command}"
                f"{payload_line}"
                f"{notify_line}\n"
                f"     last: {last_run}{status_str}  next: {next_run}"
            )
        return ToolResult(output="\n".join(lines))
