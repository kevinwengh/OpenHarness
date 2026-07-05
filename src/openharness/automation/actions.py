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
    """Bounded JSON-safe outcome returned by every automation action.

    Retry and uncertain-outcome flags are persisted by ``WorkflowRunner`` and
    therefore form part of the recovery contract, not merely display metadata.
    """

    output: Any = None
    is_error: bool = False
    error_category: str = "action_error"
    error_message: str = ""
    retryable: bool = False
    outcome_unknown: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject non-JSON, oversized, or internally inconsistent outcomes."""

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
    """Host capabilities and idempotency identities for one action attempt.

    The context deliberately carries resolved capabilities instead of secrets.
    ``allowed_tools`` remains authoritative even when an executor exposes a
    larger installed registry.
    """

    run: WorkflowRun
    step_id: str
    logical_idempotency_key: str
    attempt_idempotency_key: str
    allowed_tools: frozenset[str]
    governed_tool_executor: GovernedToolExecutor | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AutomationAction(ABC):
    """Typed asynchronous effect that can be registered with a workflow host."""

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
        """Return whether replaying these exact validated arguments is safe."""

        del arguments
        return False


@dataclass(frozen=True)
class PreparedAction:
    """Validated action invocation plus its pre-effect retry classification."""

    action: AutomationAction
    arguments: BaseModel
    retry_safe: bool


class ActionRegistry:
    """Exact-name registry for host-provided automation effects.

    Registration rejects duplicates so a plugin cannot silently replace a
    built-in effect or change the meaning of a persisted workflow definition.
    """

    def __init__(self) -> None:
        """Initialize an empty action registry owned by one workflow host."""

        self._actions: dict[str, AutomationAction] = {}

    def register(self, action: AutomationAction) -> None:
        """Register one unique action implementation by its stable name."""

        if action.name in self._actions:
            raise ValueError(f"automation action already registered: {action.name}")
        self._actions[action.name] = action

    def get(self, name: str) -> AutomationAction | None:
        """Return an exact-name action without dynamic imports or fallback."""

        return self._actions.get(name)

    def prepare(self, name: str, arguments: dict[str, Any]) -> PreparedAction:
        """Resolve, validate, and classify an action before an attempt starts."""

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
        """Execute a previously prepared action with host-owned capabilities."""

        return await prepared.action.execute(prepared.arguments, context)

    def names(self) -> tuple[str, ...]:
        """Return registered action names in deterministic order."""

        return tuple(sorted(self._actions))


class GovernedToolActionInput(BaseModel):
    """Strict workflow input selecting one installed tool and its raw arguments."""

    model_config = {"extra": "forbid"}

    tool: str = Field(min_length=1, max_length=256)
    input: dict[str, Any] = Field(default_factory=dict)


class GovernedToolAction(AutomationAction):
    """Adapt an installed ``BaseTool`` into the automation action contract.

    Workflow policy is checked before the shared governed executor runs, giving
    automation both its declarative allowlist and normal OpenHarness permission,
    hook, sensitive-path, and sandbox controls.
    """

    name = "tool.execute"
    description = "Execute one installed tool through normal hooks and permission policy."
    input_model = GovernedToolActionInput

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        """Create the adapter, optionally bound to an installed tool registry."""

        self._tool_registry = tool_registry

    def bind_registry(self, tool_registry: ToolRegistry | None) -> None:
        """Bind the host-owned registry used for conservative retry classification."""

        self._tool_registry = tool_registry

    def is_retry_safe(self, arguments: GovernedToolActionInput) -> bool:
        """Delegate replay safety to the selected tool's validated invocation."""

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
        """Enforce workflow policy and execute the selected governed tool."""

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
