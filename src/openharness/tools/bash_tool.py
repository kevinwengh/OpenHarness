"""Shell command execution tool.

Integration: This module participates in model-callable tools registered with the shared engine
governance path.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve Pydantic schemas, async ToolResult behavior, read-only policy,
context.cwd, hooks, sandboxing, output bounds, and registration.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field

from openharness.sandbox import SandboxUnavailableError
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.utils.shell import create_shell_subprocess


_READ_REMAINING_OUTPUT_TIMEOUT_SECONDS = 2.0


class BashToolInput(BaseModel):
    """Arguments for the bash tool.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    command: str = Field(description="Shell command to execute")
    cwd: str | None = Field(default=None, description="Working directory override")
    timeout_seconds: int = Field(default=600, ge=1, le=600)


class BashTool(BaseTool):
    """Execute a shell command with stdout/stderr capture.

    Integration: Constructed or referenced by ``create_default_tool_registry``.

    Event loop: Async methods ``execute`` run on their caller's loop; instances must retain
    clear task, cancellation, and cleanup ownership.

    Change safety: Keep the input schema, read-only classification, async ``ToolResult``
    contract, permission metadata, hooks, sandbox behavior, and registration synchronized.
    """

    name = "bash"
    description = "Run a shell command in the local repository."
    input_model = BashToolInput

    async def execute(self, arguments: BashToolInput, context: ToolExecutionContext) -> ToolResult:
        """Execute one model-requested ``BashTool`` invocation.

        Integration: Exposed through ``BashTool`` and collaborates with
        ``_preflight_interactive_command``, ``_format_output``, ``ToolResult``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve the asynchronous ``ToolResult`` contract, ``context.cwd``, and
        normalized operational failures; preserve permission, hook, sandbox, metadata, and
        output-size assumptions; preserve argv boundaries, timeouts, and child cleanup; preserve
        exception and fallback behavior expected by callers.

        Tool contract: The engine validates the Pydantic input and applies hooks and permission
        policy before awaiting this method. Return ``ToolResult`` for expected operational
        failures, resolve paths from ``context.cwd``, keep output and metadata serializable and
        bounded, and do not block the event loop. Revisit sandbox routing, secret redaction,
        tool-result replay, and registration whenever execution behavior changes.
        """
        cwd = Path(arguments.cwd).expanduser() if arguments.cwd else context.cwd
        preflight_error = _preflight_interactive_command(arguments.command)
        if preflight_error is not None:
            return ToolResult(
                output=preflight_error,
                is_error=True,
                metadata={"interactive_required": True},
            )
        process: asyncio.subprocess.Process | None = None
        try:
            process = await create_shell_subprocess(
                arguments.command,
                cwd=cwd,
                prefer_pty=True,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except SandboxUnavailableError as exc:
            return ToolResult(output=str(exc), is_error=True)
        except asyncio.CancelledError:
            if process is not None:
                await _terminate_process(process, force=False)
            raise

        try:
            await asyncio.wait_for(process.wait(), timeout=arguments.timeout_seconds)
        except asyncio.TimeoutError:
            output_buffer = await _drain_available_output(process.stdout)
            await _terminate_process(process, force=True)
            output_buffer.extend(await _read_remaining_output(process))
            return ToolResult(
                output=_format_timeout_output(
                    output_buffer,
                    command=arguments.command,
                    timeout_seconds=arguments.timeout_seconds,
                ),
                is_error=True,
                metadata={"returncode": process.returncode, "timed_out": True},
            )
        except asyncio.CancelledError:
            await _terminate_process(process, force=False)
            raise

        output_buffer = await _read_remaining_output(process)
        text = _format_output(output_buffer)
        return ToolResult(
            output=text,
            is_error=process.returncode != 0,
            metadata={"returncode": process.returncode},
        )


async def _terminate_process(process: asyncio.subprocess.Process, *, force: bool) -> None:
    """Run the terminate process workflow through its asynchronous collaborators.

    Integration: Used as an internal helper or callback at this module boundary and collaborates
    with ``process.terminate``, ``process.kill``, ``process.wait``.

    Event loop: This coroutine coordinates child tasks; preserve cancellation, completion, and
    exception ownership.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if process.returncode is not None:
        return
    if force:
        process.kill()
        await process.wait()
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


async def _read_remaining_output(process: asyncio.subprocess.Process) -> bytearray:
    """Read remaining output for the enclosing subsystem.

    Integration: Called by ``BashTool.execute`` and collaborates with ``bytearray``,
    ``output_buffer.extend``, ``asyncio.wait_for``.

    Event loop: This coroutine coordinates child tasks; preserve cancellation, completion, and
    exception ownership.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    output_buffer = bytearray()
    if process.stdout is not None:
        try:
            remaining = await asyncio.wait_for(
                process.stdout.read(),
                timeout=_READ_REMAINING_OUTPUT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            remaining = b""
        output_buffer.extend(remaining)
    return output_buffer


async def _drain_available_output(
    stream: asyncio.StreamReader | None,
    *,
    read_timeout: float = 0.05,
) -> bytearray:
    """Run the drain available output workflow through its asynchronous collaborators.

    Integration: Called by ``BashTool.execute`` and collaborates with ``bytearray``,
    ``output_buffer.extend``, ``asyncio.wait_for``.

    Event loop: This coroutine coordinates child tasks; preserve cancellation, completion, and
    exception ownership.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    output_buffer = bytearray()
    if stream is None:
        return output_buffer
    while True:
        try:
            chunk = await asyncio.wait_for(stream.read(65536), timeout=read_timeout)
        except asyncio.TimeoutError:
            return output_buffer
        if not chunk:
            return output_buffer
        output_buffer.extend(chunk)


def _format_output(output_buffer: bytearray) -> str:
    """Format output for the enclosing subsystem.

    Integration: Called by ``BashTool.execute``, ``_format_timeout_output`` and collaborates
    with ``strip``, ``replace``, ``output_buffer.decode``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    text = output_buffer.decode("utf-8", errors="replace").replace("\r\n", "\n").strip()
    if not text:
        return "(no output)"
    if len(text) > 12000:
        return f"{text[:12000]}\n...[truncated]..."
    return text


def _format_timeout_output(output_buffer: bytearray, *, command: str, timeout_seconds: int) -> str:
    """Format timeout output for the enclosing subsystem.

    Integration: Called by ``BashTool.execute`` and collaborates with ``_format_output``,
    ``_interactive_command_hint``, ``join``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    parts = [f"Command timed out after {timeout_seconds} seconds."]
    text = _format_output(output_buffer)
    if text != "(no output)":
        parts.extend(["", "Partial output:", text])
    hint = _interactive_command_hint(command=command, output=text)
    if hint:
        parts.extend(["", hint])
    return "\n".join(parts)


def _preflight_interactive_command(command: str) -> str | None:
    """Derive preflight interactive command from the current inputs and subsystem state.

    Integration: Called by ``BashTool.execute`` and collaborates with ``command.lower``,
    ``_looks_like_interactive_scaffold``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    lowered_command = command.lower()
    if not _looks_like_interactive_scaffold(lowered_command):
        return None
    return (
        "This command appears to require interactive input before it can continue. "
        "The bash tool is non-interactive, so it cannot answer installer/scaffold prompts live. "
        "Prefer non-interactive flags (for example --yes, -y, --skip-install, --defaults, --non-interactive), "
        "or run the scaffolding step once in an external terminal before asking the agent to continue."
    )


def _interactive_command_hint(*, command: str, output: str) -> str | None:
    """Derive interactive command hint from the current inputs and subsystem state.

    Integration: Called by ``_format_timeout_output`` and collaborates with ``command.lower``,
    ``_looks_like_interactive_scaffold``, ``_looks_like_prompt``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    lowered_command = command.lower()
    if _looks_like_interactive_scaffold(lowered_command) or _looks_like_prompt(output):
        return (
            "This command appears to require interactive input. "
            "The bash tool is non-interactive, so prefer non-interactive flags "
            "(for example --yes, -y, --skip-install, or similar) or run the "
            "scaffolding step once in an external terminal before continuing."
        )
    return None


def _looks_like_interactive_scaffold(lowered_command: str) -> bool:
    """Determine whether looks like interactive scaffold holds for the current inputs.

    Integration: Called by ``_preflight_interactive_command``, ``_interactive_command_hint`` and
    collaborates with ``any``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    scaffold_markers: tuple[str, ...] = (
        "create-next-app",
        "npm create ",
        "pnpm create ",
        "yarn create ",
        "bun create ",
        "pnpm dlx ",
        "npm init ",
        "pnpm init ",
        "yarn init ",
        "bunx create-",
        "npx create-",
    )
    non_interactive_markers: tuple[str, ...] = (
        "--yes",
        " -y",
        "--skip-install",
        "--defaults",
        "--non-interactive",
        "--ci",
    )
    return any(marker in lowered_command for marker in scaffold_markers) and not any(
        marker in lowered_command for marker in non_interactive_markers
    )


def _looks_like_prompt(output: str) -> bool:
    """Determine whether looks like prompt holds for the current inputs.

    Integration: Called by ``_interactive_command_hint`` and collaborates with ``output.lower``,
    ``any``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if not output:
        return False
    prompt_markers: Iterable[str] = (
        "would you like",
        "ok to proceed",
        "select an option",
        "which",
        "press enter to continue",
        "?",
    )
    lowered_output = output.lower()
    return any(marker in lowered_output for marker in prompt_markers)
