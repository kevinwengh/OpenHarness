"""Tool for producing a brief summary.

Integration: This module participates in model-callable tools registered with the shared engine
governance path.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve Pydantic schemas, async ToolResult behavior, read-only policy,
context.cwd, hooks, sandboxing, output bounds, and registration.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class BriefToolInput(BaseModel):
    """Arguments for brief mode transformation.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    text: str = Field(description="Text to shorten")
    max_chars: int = Field(default=200, ge=20, le=2000)


class BriefTool(BaseTool):
    """Return a shortened version of text.

    Integration: Constructed or referenced by ``create_default_tool_registry``.

    Event loop: Async methods ``execute`` run on their caller's loop; instances must retain
    clear task, cancellation, and cleanup ownership.

    Change safety: Keep the input schema, read-only classification, async ``ToolResult``
    contract, permission metadata, hooks, sandbox behavior, and registration synchronized.
    """

    name = "brief"
    description = "Shorten a piece of text for compact display."
    input_model = BriefToolInput

    def is_read_only(self, arguments: BriefToolInput) -> bool:
        """Classify whether this ``BriefTool`` invocation can mutate state.

        Integration: Exposed through ``BriefTool``.

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

    async def execute(self, arguments: BriefToolInput, context: ToolExecutionContext) -> ToolResult:
        """Execute one model-requested ``BriefTool`` invocation.

        Integration: Exposed through ``BriefTool`` and collaborates with ``ToolResult``,
        ``rstrip``.

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
        text = arguments.text.strip()
        if len(text) <= arguments.max_chars:
            return ToolResult(output=text)
        return ToolResult(output=text[: arguments.max_chars].rstrip() + "...")
