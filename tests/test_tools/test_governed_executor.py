from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from openharness.config.settings import PermissionSettings
from openharness.hooks.events import HookEvent
from openharness.hooks.types import AggregatedHookResult, HookResult
from openharness.permissions import PermissionChecker, PermissionMode
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from openharness.tools.executor import GovernedToolExecutor


class Input(BaseModel):
    path: str
    value: str = "ok"


class RecordingTool(BaseTool):
    name = "recording"
    description = "Record one governed invocation."
    input_model = Input

    def __init__(self, *, read_only: bool = False, raises: bool = False) -> None:
        self.read_only = read_only
        self.raises = raises
        self.calls: list[tuple[Input, ToolExecutionContext]] = []

    async def execute(self, arguments: Input, context: ToolExecutionContext) -> ToolResult:
        self.calls.append((arguments, context))
        if self.raises:
            raise RuntimeError("boom")
        return ToolResult(output=arguments.value, metadata={"recorded": True})

    def is_read_only(self, arguments: Input) -> bool:
        del arguments
        return self.read_only


class RecordingHooks:
    def __init__(self, *, block: bool = False) -> None:
        self.block = block
        self.calls: list[tuple[HookEvent, dict]] = []

    async def execute(self, event: HookEvent, payload: dict) -> AggregatedHookResult:
        self.calls.append((event, payload))
        if event == HookEvent.PRE_TOOL_USE and self.block:
            return AggregatedHookResult(
                [HookResult(hook_type="test", success=False, blocked=True, reason="blocked")]
            )
        return AggregatedHookResult()


def _executor(
    tmp_path: Path,
    tool: RecordingTool,
    *,
    settings: PermissionSettings | None = None,
    hooks=None,
    permission_prompt=None,
    output_transform=None,
) -> GovernedToolExecutor:
    registry = ToolRegistry()
    registry.register(tool)
    return GovernedToolExecutor(
        registry=registry,
        permission_checker=PermissionChecker(settings or PermissionSettings()),
        cwd=tmp_path,
        hook_executor=hooks,
        permission_prompt=permission_prompt,
        metadata={"custom": "metadata"},
        output_transform=output_transform,
    )


@pytest.mark.asyncio
async def test_executor_preserves_hook_permission_execution_and_output_order(tmp_path: Path) -> None:
    tool = RecordingTool(read_only=True)
    hooks = RecordingHooks()
    executor = _executor(
        tmp_path,
        tool,
        hooks=hooks,
        output_transform=lambda name, invocation, output: (f"{name}:{invocation}:{output}", None),
    )

    outcome = await executor.execute(
        "recording",
        {"path": "file.txt", "value": "done"},
        invocation_id="call-1",
    )

    assert outcome.output == "recording:call-1:done"
    assert outcome.metadata == {"recorded": True}
    assert outcome.resolved_file_path == str((tmp_path / "file.txt").resolve())
    assert [event for event, _ in hooks.calls] == [HookEvent.PRE_TOOL_USE, HookEvent.POST_TOOL_USE]
    assert tool.calls[0][1].metadata["custom"] == "metadata"


@pytest.mark.asyncio
async def test_executor_blocks_hook_unknown_invalid_and_sensitive_path(tmp_path: Path) -> None:
    tool = RecordingTool(read_only=True)
    blocked = await _executor(tmp_path, tool, hooks=RecordingHooks(block=True)).execute(
        "recording", {"path": "file.txt"}, invocation_id="blocked"
    )
    assert blocked.is_error is True
    assert blocked.output == "blocked"
    assert tool.calls == []

    executor = _executor(tmp_path, tool)
    unknown = await executor.execute("missing", {}, invocation_id="unknown")
    invalid = await executor.execute("recording", {}, invocation_id="invalid")
    sensitive = await executor.execute(
        "recording",
        {"path": str(tmp_path / ".ssh" / "id_rsa")},
        invocation_id="sensitive",
    )
    assert unknown.is_error and "Unknown tool" in unknown.output
    assert invalid.is_error and "Invalid input" in invalid.output
    assert sensitive.is_error and "sensitive credential" in sensitive.output


@pytest.mark.asyncio
async def test_executor_requires_and_honors_confirmation(tmp_path: Path) -> None:
    tool = RecordingTool(read_only=False)
    denied = await _executor(tmp_path, tool).execute(
        "recording", {"path": "file.txt"}, invocation_id="denied"
    )
    assert denied.is_error is True
    assert tool.calls == []

    prompts: list[tuple[str, str]] = []

    async def approve(name: str, reason: str) -> bool:
        prompts.append((name, reason))
        return True

    allowed = await _executor(tmp_path, tool, permission_prompt=approve).execute(
        "recording", {"path": "file.txt"}, invocation_id="allowed"
    )
    assert allowed.is_error is False
    assert prompts and prompts[0][0] == "recording"


@pytest.mark.asyncio
async def test_executor_normalizes_tool_exception(tmp_path: Path) -> None:
    tool = RecordingTool(read_only=True, raises=True)
    outcome = await _executor(tmp_path, tool).execute(
        "recording", {"path": "file.txt"}, invocation_id="failure"
    )
    assert outcome.is_error is True
    assert outcome.output == "Tool recording failed: RuntimeError: boom"


def test_registry_filtered_exposes_only_installed_selected_tools() -> None:
    first = RecordingTool(read_only=True)
    second = RecordingTool(read_only=True)
    second.name = "second"
    registry = ToolRegistry()
    registry.register(first)
    registry.register(second)

    filtered = registry.filtered(["second", "missing"])

    assert filtered.get("recording") is None
    assert filtered.get("second") is second


@pytest.mark.asyncio
async def test_explicit_allow_still_cannot_bypass_sensitive_path(tmp_path: Path) -> None:
    tool = RecordingTool(read_only=False)
    settings = PermissionSettings(
        mode=PermissionMode.DEFAULT,
        allowed_tools=["recording"],
    )
    outcome = await _executor(tmp_path, tool, settings=settings).execute(
        "recording",
        {"path": str(tmp_path / ".ssh" / "id_ed25519")},
        invocation_id="sensitive",
    )
    assert outcome.is_error is True
    assert tool.calls == []
