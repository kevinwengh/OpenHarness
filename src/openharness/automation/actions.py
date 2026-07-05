"""Typed host-action registry and governed-tool workflow adapter."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from openharness.automation.models import validate_json_value
from openharness.automation.state import WorkflowRun
from openharness.tools.base import ToolRegistry
from openharness.tools.executor import GovernedToolExecutor

MAX_ACTION_RESULT_BYTES = 256 * 1024


@dataclass(frozen=True)
class ActionResult:
    output: Any = None
    is_error: bool = False
    error_category: str = "action_error"
    error_message: str = ""
    retryable: bool = False
    outcome_unknown: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_json_value(self.output, path="action output")
        validate_json_value(self.metadata, path="action metadata")
        encoded = json.dumps(
            {"output": self.output, "metadata": self.metadata},
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > MAX_ACTION_RESULT_BYTES:
            raise ValueError(f"action result exceeds {MAX_ACTION_RESULT_BYTES} bytes")
        if not self.error_category.strip():
            raise ValueError("action error_category cannot be empty")
        if not self.is_error and (self.retryable or self.outcome_unknown):
            raise ValueError("successful actions cannot be retryable or outcome_unknown")
        if self.outcome_unknown and not self.is_error:
            raise ValueError("outcome_unknown requires an action error")


@dataclass(frozen=True)
class ActionExecutionContext:
    run: WorkflowRun
    step_id: str
    logical_idempotency_key: str
    attempt_idempotency_key: str
    allowed_tools: frozenset[str]
    governed_tool_executor: GovernedToolExecutor | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AutomationAction(ABC):
    name: str
    description: str
    input_model: type[BaseModel]

    @abstractmethod
    async def execute(
        self,
        arguments: BaseModel,
        context: ActionExecutionContext,
    ) -> ActionResult:
        """Execute one validated workflow action."""

    def is_retry_safe(self, arguments: BaseModel) -> bool:
        del arguments
        return False


@dataclass(frozen=True)
class PreparedAction:
    action: AutomationAction
    arguments: BaseModel
    retry_safe: bool


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, AutomationAction] = {}

    def register(self, action: AutomationAction) -> None:
        if action.name in self._actions:
            raise ValueError(f"automation action already registered: {action.name}")
        self._actions[action.name] = action

    def get(self, name: str) -> AutomationAction | None:
        return self._actions.get(name)

    def prepare(self, name: str, arguments: dict[str, Any]) -> PreparedAction:
        action = self.get(name)
        if action is None:
            raise ValueError(f"unknown automation action: {name}")
        parsed = action.input_model.model_validate(arguments)
        return PreparedAction(action, parsed, action.is_retry_safe(parsed))

    async def execute(
        self,
        prepared: PreparedAction,
        context: ActionExecutionContext,
    ) -> ActionResult:
        return await prepared.action.execute(prepared.arguments, context)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._actions))


class GovernedToolActionInput(BaseModel):
    model_config = {"extra": "forbid"}

    tool: str = Field(min_length=1, max_length=256)
    input: dict[str, Any] = Field(default_factory=dict)


class GovernedToolAction(AutomationAction):
    name = "tool.execute"
    description = "Execute one installed tool through normal hooks and permission policy."
    input_model = GovernedToolActionInput

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        self._tool_registry = tool_registry

    def is_retry_safe(self, arguments: GovernedToolActionInput) -> bool:
        if self._tool_registry is None:
            return False
        tool = self._tool_registry.get(arguments.tool)
        if tool is None:
            return False
        try:
            parsed = tool.input_model.model_validate(arguments.input)
        except Exception:
            return False
        return tool.is_read_only(parsed)

    async def execute(
        self,
        arguments: GovernedToolActionInput,
        context: ActionExecutionContext,
    ) -> ActionResult:
        if arguments.tool not in context.allowed_tools:
            return ActionResult(
                is_error=True,
                error_category="tool_policy_denied",
                error_message=f"tool {arguments.tool!r} is not allowed by the workflow",
            )
        if context.governed_tool_executor is None:
            return ActionResult(
                is_error=True,
                error_category="tool_executor_unavailable",
                error_message="governed tool execution is unavailable in this host",
            )
        tool = context.governed_tool_executor.registry.get(arguments.tool)
        if tool is None:
            return ActionResult(
                is_error=True,
                error_category="unknown_tool",
                error_message=f"installed tool not found: {arguments.tool}",
            )
        outcome = await context.governed_tool_executor.execute(
            arguments.tool,
            arguments.input,
            invocation_id=context.attempt_idempotency_key,
        )
        if outcome.is_error:
            return ActionResult(
                output={"content": outcome.output, "metadata": outcome.metadata},
                is_error=True,
                error_category="tool_error",
                error_message=outcome.output,
                retryable=False,
            )
        return ActionResult(
            output={"content": outcome.output, "metadata": outcome.metadata},
            metadata={
                "artifact_path": str(outcome.artifact_path) if outcome.artifact_path else None
            },
        )
