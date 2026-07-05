from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from openharness.automation.actions import (
    ActionExecutionContext,
    ActionRegistry,
    GovernedToolAction,
)
from openharness.automation.store import AutomationStore
from openharness.config.settings import PermissionSettings
from openharness.permissions import PermissionChecker, PermissionMode
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from openharness.tools.executor import GovernedToolExecutor


class EchoInput(BaseModel):
    value: str


class EchoTool(BaseTool):
    name = "echo_read"
    description = "Return a value without mutation."
    input_model = EchoInput

    async def execute(self, arguments: EchoInput, context: ToolExecutionContext) -> ToolResult:
        del context
        return ToolResult(output=arguments.value)

    def is_read_only(self, arguments: EchoInput) -> bool:
        del arguments
        return True


def test_action_registry_rejects_duplicates_and_invalid_input() -> None:
    registry = ActionRegistry()
    action = GovernedToolAction()
    registry.register(action)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(action)
    with pytest.raises(ValueError, match="unknown automation action"):
        registry.prepare("missing", {})
    with pytest.raises(ValueError):
        registry.prepare("tool.execute", {"tool": ""})


@pytest.mark.asyncio
async def test_governed_tool_action_enforces_workflow_allowlist(
    tmp_path: Path,
    workflow,
    channel_event,
) -> None:
    tool_registry = ToolRegistry()
    tool_registry.register(EchoTool())
    executor = GovernedToolExecutor(
        registry=tool_registry,
        permission_checker=PermissionChecker(
            PermissionSettings(mode=PermissionMode.DEFAULT, allowed_tools=["echo_read"])
        ),
        cwd=tmp_path,
    )
    run = AutomationStore(tmp_path / "automation").reserve(workflow, channel_event).run
    action = GovernedToolAction(tool_registry)
    parsed = action.input_model(tool="echo_read", input={"value": "hello"})
    base_context = dict(
        run=run,
        step_id="notify",
        logical_idempotency_key="logical",
        attempt_idempotency_key="attempt",
        governed_tool_executor=executor,
    )

    denied = await action.execute(
        parsed,
        ActionExecutionContext(allowed_tools=frozenset(), **base_context),
    )
    allowed = await action.execute(
        parsed,
        ActionExecutionContext(allowed_tools=frozenset({"echo_read"}), **base_context),
    )

    assert denied.is_error is True
    assert denied.error_category == "tool_policy_denied"
    assert allowed.is_error is False
    assert allowed.output == {"content": "hello", "metadata": {}}


@pytest.mark.asyncio
async def test_governed_tool_permission_error_is_not_retryable(
    tmp_path: Path,
    workflow,
    channel_event,
) -> None:
    tool_registry = ToolRegistry()
    tool_registry.register(EchoTool())
    executor = GovernedToolExecutor(
        registry=tool_registry,
        permission_checker=PermissionChecker(
            PermissionSettings(mode=PermissionMode.DEFAULT, denied_tools=["echo_read"])
        ),
        cwd=tmp_path,
    )
    run = AutomationStore(tmp_path / "automation").reserve(workflow, channel_event).run
    action = GovernedToolAction(tool_registry)
    result = await action.execute(
        action.input_model(tool="echo_read", input={"value": "hello"}),
        ActionExecutionContext(
            run=run,
            step_id="notify",
            logical_idempotency_key="logical",
            attempt_idempotency_key="attempt",
            allowed_tools=frozenset({"echo_read"}),
            governed_tool_executor=executor,
        ),
    )
    assert result.is_error is True
    assert result.retryable is False
