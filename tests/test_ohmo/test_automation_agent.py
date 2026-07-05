from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ohmo.automation.agent import (
    RuntimeSkillAgentExecutor,
    _automation_permission_settings,
)
from openharness.api.client import ApiMessageCompleteEvent
from openharness.api.usage import UsageSnapshot
from openharness.automation.models import AgentStep, AutomationEvent, WorkflowDefinition
from openharness.automation.state import new_workflow_run
from openharness.config.settings import PathRuleConfig, PermissionSettings
from openharness.engine.messages import ConversationMessage, TextBlock
from openharness.permissions import PermissionChecker, PermissionMode


class RecordingClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.requests = []

    async def stream_message(self, request):
        self.requests.append(request)
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(
                role="assistant",
                content=[TextBlock(text=self.response)],
            ),
            usage=UsageSnapshot(input_tokens=1, output_tokens=1),
            stop_reason=None,
        )


def _write_skill(workspace: Path, body: str, *, name: str = "incident-triage") -> None:
    skill_dir = workspace / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")


def _agent_step(*, skill: str = "incident-triage", allowed_tools=None) -> AgentStep:
    return AgentStep.model_validate(
        {
            "id": "assess",
            "type": "agent",
            "skill": skill,
            "allowed_tools": allowed_tools or [],
            "output_schema": {
                "summary": {"type": "string"},
                "customer_impact": {"type": "boolean"},
            },
        }
    )


def _run(step: AgentStep):
    definition = WorkflowDefinition.model_validate(
        {
            "version": 1,
            "id": "incident-routing",
            "trigger": {"event": "channel.message"},
            "policy": {"allowed_tools": step.allowed_tools},
            "steps": [step.model_dump(mode="json", by_alias=True)],
        }
    )
    event = AutomationEvent.model_validate(
        {
            "version": 1,
            "id": "event-1",
            "type": "channel.message",
            "occurred_at": datetime(2026, 7, 5, tzinfo=timezone.utc),
            "source": {"adapter": "channel", "channel": "slack"},
            "actor": {"id": "U1"},
            "payload": {"text": "Production is DOWN"},
        }
    )
    return new_workflow_run(
        definition,
        event,
        run_id="run-automation-agent-0001",
        now=datetime(2026, 7, 5, tzinfo=timezone.utc),
    )


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")


@pytest.mark.asyncio
async def test_agent_executes_named_skill_with_exact_tools_and_event_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_COORDINATOR_MODE", "1")
    workspace = tmp_path / "workspace"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    _write_skill(
        workspace,
        "# Incident triage\nClassify impact and summarize the incident precisely.\n",
    )
    client = RecordingClient(
        '{"summary":"Production is unavailable","customer_impact":true}'
    )
    step = _agent_step(allowed_tools=["read_file", "glob"])
    executor = RuntimeSkillAgentExecutor(
        workspace=workspace,
        cwd=cwd,
        api_client=client,
    )

    result = await executor.execute(step, _run(step), invocation_id="invocation-1")

    assert result.is_error is False
    assert result.output == {
        "summary": "Production is unavailable",
        "customer_impact": True,
    }
    assert len(client.requests) == 1
    request = client.requests[0]
    assert [tool["name"] for tool in request.tools] == ["read_file", "glob"]
    assert "Classify impact and summarize the incident precisely" in request.system_prompt
    assert "exactly one JSON object" in request.system_prompt
    assert any("Production is DOWN" in message.text for message in request.messages)


@pytest.mark.asyncio
async def test_agent_rejects_missing_skill_before_model_call(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    client = RecordingClient("{}")
    step = _agent_step(skill="missing-skill")
    executor = RuntimeSkillAgentExecutor(workspace=workspace, cwd=cwd, api_client=client)

    result = await executor.execute(step, _run(step), invocation_id="invocation-1")

    assert result.is_error is True
    assert result.error_category == "skill_not_found"
    assert client.requests == []


@pytest.mark.asyncio
async def test_agent_rejects_skill_disabled_for_model_invocation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    _write_skill(
        workspace,
        "---\ndisable-model-invocation: true\n---\n# Manual procedure\n",
        name="manual-only",
    )
    client = RecordingClient("{}")
    step = _agent_step(skill="manual-only")
    executor = RuntimeSkillAgentExecutor(workspace=workspace, cwd=cwd, api_client=client)

    result = await executor.execute(step, _run(step), invocation_id="invocation-1")

    assert result.is_error is True
    assert result.error_category == "skill_not_model_invocable"
    assert client.requests == []


@pytest.mark.asyncio
async def test_agent_rejects_markdown_wrapped_json(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    _write_skill(workspace, "# Incident triage\nSummarize the incident.\n")
    client = RecordingClient(
        '```json\n{"summary":"Down","customer_impact":true}\n```'
    )
    step = _agent_step()
    executor = RuntimeSkillAgentExecutor(workspace=workspace, cwd=cwd, api_client=client)

    result = await executor.execute(step, _run(step), invocation_id="invocation-1")

    assert result.is_error is True
    assert result.error_category == "invalid_agent_json"


@pytest.mark.asyncio
async def test_agent_rejects_unavailable_allowed_tool(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    _write_skill(workspace, "# Incident triage\nSummarize the incident.\n")
    client = RecordingClient("{}")
    step = _agent_step(allowed_tools=["missing_tool"])
    executor = RuntimeSkillAgentExecutor(workspace=workspace, cwd=cwd, api_client=client)

    result = await executor.execute(step, _run(step), invocation_id="invocation-1")

    assert result.is_error is True
    assert result.error_category == "agent_setup_error"
    assert "unavailable tools: missing_tool" in result.error_message
    assert client.requests == []


def test_automation_permission_allows_filtered_tools_but_preserves_denials() -> None:
    settings = _automation_permission_settings(
        PermissionSettings(
            mode=PermissionMode.DEFAULT,
            denied_tools=["bash"],
            path_rules=[PathRuleConfig(pattern="*/private/*", allow=False)],
            denied_commands=["rm *"],
        )
    )
    checker = PermissionChecker(settings)

    assert checker.evaluate("write_file", is_read_only=False).allowed is True
    assert checker.evaluate("bash", is_read_only=False, command="echo ok").allowed is False
    assert (
        checker.evaluate(
            "write_file",
            is_read_only=False,
            file_path="/repo/private/data.txt",
        ).allowed
        is False
    )
    assert checker.evaluate("shell", is_read_only=False, command="rm file").allowed is False
