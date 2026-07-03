"""Tool for reading and updating settings.

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

from openharness.config.settings import load_settings, save_settings
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class ConfigToolInput(BaseModel):
    """Arguments for config access.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    action: str = Field(default="show", description="show or set")
    key: str | None = Field(default=None)
    value: str | None = Field(default=None)


class ConfigTool(BaseTool):
    """Read or update OpenHarness settings.

    Integration: Constructed or referenced by ``create_default_tool_registry``.

    Event loop: Async methods ``execute`` run on their caller's loop; instances must retain
    clear task, cancellation, and cleanup ownership.

    Change safety: Keep the input schema, read-only classification, async ``ToolResult``
    contract, permission metadata, hooks, sandbox behavior, and registration synchronized.
    """

    name = "config"
    description = "Read or update OpenHarness settings."
    input_model = ConfigToolInput

    async def execute(self, arguments: ConfigToolInput, context: ToolExecutionContext) -> ToolResult:
        """Execute one model-requested ``ConfigTool`` invocation.

        Integration: Exposed through ``ConfigTool`` and collaborates with ``load_settings``,
        ``ToolResult``, ``save_settings``.

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
        del context
        settings = load_settings()
        if arguments.action == "show":
            return ToolResult(output=settings.model_dump_json(indent=2))
        if arguments.action == "set" and arguments.key and arguments.value is not None:
            target: Any = settings
            parts = arguments.key.split(".")
            for part in parts[:-1]:
                if not hasattr(target, part):
                    return ToolResult(output=f"Unknown config key: {arguments.key}", is_error=True)
                target = getattr(target, part)
            leaf = parts[-1]
            if not hasattr(target, leaf):
                return ToolResult(output=f"Unknown config key: {arguments.key}", is_error=True)
            current = getattr(target, leaf)
            value: Any = arguments.value
            if isinstance(current, bool):
                value = arguments.value.strip().lower() in {"1", "true", "yes", "on"}
            elif isinstance(current, int) and not isinstance(current, bool):
                value = int(arguments.value)
            elif isinstance(current, float):
                value = float(arguments.value)
            setattr(target, leaf, value)
            save_settings(settings)
            return ToolResult(output=f"Updated {arguments.key}")
        return ToolResult(output="Usage: action=show or action=set with key/value", is_error=True)
