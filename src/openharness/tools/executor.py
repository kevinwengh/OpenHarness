"""Reusable governed execution for model-requested and workflow-requested tools."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from openharness.hooks import HookEvent, HookExecutor
from openharness.permissions.checker import PermissionChecker
from openharness.tools.base import ToolExecutionContext, ToolRegistry

log = logging.getLogger(__name__)

PermissionPrompt = Callable[[str, str], Awaitable[bool]]
AskUserPrompt = Callable[[str], Awaitable[str]]
OutputTransform = Callable[[str, str, str], tuple[str, Path | None]]


@dataclass(frozen=True)
class GovernedToolOutcome:
    """Normalized host-independent result of one governed tool invocation.

    The engine adapter converts this into a provider ``ToolResultBlock`` while
    automation adapters convert it into their own durable action result. Paths
    are included only for already-evaluated permission and artifact state.
    """

    output: str
    is_error: bool
    metadata: dict[str, Any] = field(default_factory=dict)
    resolved_file_path: str | None = None
    artifact_path: Path | None = None


ResultObserver = Callable[[str, dict[str, object], GovernedToolOutcome], None]


class GovernedToolExecutor:
    """Apply the shared safety sequence to model- and workflow-requested tools.

    Integration: ``engine.query`` and automation hosts configure this executor
    with their registry, policy, hooks, and output observer rather than
    duplicating the governance path.

    Event loop: ``execute`` awaits hooks, prompts, and the tool on the caller's
    loop. Synchronous transforms and observers must remain bounded.

    Change safety: Preserve pre-hook, lookup, validation, permission, execution,
    output transform, result observer, and post-hook ordering.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        permission_checker: PermissionChecker,
        cwd: str | Path,
        hook_executor: HookExecutor | None = None,
        permission_prompt: PermissionPrompt | None = None,
        ask_user_prompt: AskUserPrompt | None = None,
        metadata: dict[str, object] | None = None,
        output_transform: OutputTransform | None = None,
        result_observer: ResultObserver | None = None,
    ) -> None:
        """Bind host-owned governance collaborators for subsequent invocations.

        ``result_observer`` runs after output normalization and before the post
        hook so hosts can checkpoint state using the historical engine ordering.
        The executor does not own or close any supplied collaborator.
        """
        self.registry = registry
        self.permission_checker = permission_checker
        self.cwd = Path(cwd).expanduser().resolve()
        self.hook_executor = hook_executor
        self.permission_prompt = permission_prompt
        self.ask_user_prompt = ask_user_prompt
        self.metadata = metadata or {}
        self.output_transform = output_transform
        self.result_observer = result_observer

    async def execute(
        self,
        tool_name: str,
        tool_input: dict[str, object],
        *,
        invocation_id: str,
    ) -> GovernedToolOutcome:
        """Execute one exact-name tool call through the shared governance sequence.

        Unknown tools, invalid input, denials, and tool exceptions become error
        outcomes. Cancellation still propagates, and every accepted call uses a
        validated Pydantic input plus a resolved ``ToolExecutionContext``.
        """

        if self.hook_executor is not None:
            pre_hooks = await self.hook_executor.execute(
                HookEvent.PRE_TOOL_USE,
                {
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "event": HookEvent.PRE_TOOL_USE.value,
                },
            )
            if pre_hooks.blocked:
                return GovernedToolOutcome(
                    output=pre_hooks.reason or f"pre_tool_use hook blocked {tool_name}",
                    is_error=True,
                )

        log.debug("tool_call start: %s id=%s", tool_name, invocation_id)
        tool = self.registry.get(tool_name)
        if tool is None:
            log.warning("unknown tool: %s", tool_name)
            return GovernedToolOutcome(output=f"Unknown tool: {tool_name}", is_error=True)

        try:
            parsed_input = tool.input_model.model_validate(tool_input)
        except Exception as exc:
            log.warning("invalid input for %s: %s", tool_name, exc)
            return GovernedToolOutcome(
                output=f"Invalid input for {tool_name}: {exc}",
                is_error=True,
            )

        file_path = resolve_permission_file_path(self.cwd, tool_input, parsed_input)
        command = extract_permission_command(tool_input, parsed_input)
        is_read_only = tool.is_read_only(parsed_input)
        decision = self.permission_checker.evaluate(
            tool_name,
            is_read_only=is_read_only,
            file_path=file_path,
            command=command,
        )
        if not decision.allowed:
            if decision.requires_confirmation and self.permission_prompt is not None:
                if self.hook_executor is not None:
                    await self.hook_executor.execute(
                        HookEvent.NOTIFICATION,
                        {
                            "event": HookEvent.NOTIFICATION.value,
                            "notification_type": "permission_prompt",
                            "tool_name": tool_name,
                            "reason": decision.reason,
                        },
                    )
                if not await self.permission_prompt(tool_name, decision.reason):
                    return GovernedToolOutcome(
                        output=decision.reason or f"Permission denied for {tool_name}",
                        is_error=True,
                        resolved_file_path=file_path,
                    )
            else:
                return GovernedToolOutcome(
                    output=decision.reason or f"Permission denied for {tool_name}",
                    is_error=True,
                    resolved_file_path=file_path,
                )

        started = time.monotonic()
        try:
            result = await tool.execute(
                parsed_input,
                ToolExecutionContext(
                    cwd=self.cwd,
                    metadata={
                        "tool_registry": self.registry,
                        "ask_user_prompt": self.ask_user_prompt,
                        **self.metadata,
                    },
                    hook_executor=self.hook_executor,
                ),
            )
        except Exception as exc:
            log.exception("tool execution raised: name=%s id=%s", tool_name, invocation_id)
            return GovernedToolOutcome(
                output=f"Tool {tool_name} failed: {type(exc).__name__}: {exc}",
                is_error=True,
                resolved_file_path=file_path,
            )
        log.debug(
            "executed %s in %.2fs err=%s output_len=%d",
            tool_name,
            time.monotonic() - started,
            result.is_error,
            len(result.output or ""),
        )

        output = result.output
        artifact_path: Path | None = None
        if self.output_transform is not None:
            output, artifact_path = self.output_transform(tool_name, invocation_id, output)
        outcome = GovernedToolOutcome(
            output=output,
            is_error=result.is_error,
            metadata=dict(result.metadata or {}),
            resolved_file_path=file_path,
            artifact_path=artifact_path,
        )
        if self.result_observer is not None:
            self.result_observer(tool_name, tool_input, outcome)
        if self.hook_executor is not None:
            await self.hook_executor.execute(
                HookEvent.POST_TOOL_USE,
                {
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "tool_output": outcome.output,
                    "tool_is_error": outcome.is_error,
                    "event": HookEvent.POST_TOOL_USE.value,
                },
            )
        return outcome


def resolve_permission_file_path(
    cwd: Path,
    raw_input: dict[str, object],
    parsed_input: object,
) -> str | None:
    """Resolve common raw or validated path fields for permission evaluation.

    Raw input is checked first for compatibility with plugin schemas. This
    helper never rewrites the arguments passed to the tool.
    """

    for key in ("file_path", "path", "root"):
        value = raw_input.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = cwd / path
            return str(path.resolve())
    for attr in ("file_path", "path", "root"):
        value = getattr(parsed_input, attr, None)
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = cwd / path
            return str(path.resolve())
    return None


def extract_permission_command(
    raw_input: dict[str, object],
    parsed_input: object,
) -> str | None:
    """Return the raw or validated command used by command-deny policy.

    Extraction is deliberately side-effect free: permission policy observes the
    same command string that the tool will later receive.
    """

    value = raw_input.get("command")
    if isinstance(value, str) and value.strip():
        return value
    value = getattr(parsed_input, "command", None)
    if isinstance(value, str) and value.strip():
        return value
    return None
