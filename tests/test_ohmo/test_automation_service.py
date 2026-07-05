from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from ohmo.automation.actions import _resolve_media_paths
from ohmo.automation.events import channel_message_event
from ohmo.automation.service import AutomationDispatch, OhmoAutomationService
from ohmo.gateway.bridge import OhmoGatewayBridge
from ohmo.memory import add_memory_entry
from openharness.automation.runner import AgentStepResult
from openharness.channels.bus.events import InboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.memory.schema import split_memory_file


class StaticAgent:
    def __init__(self, output: dict) -> None:
        self.output = output
        self.calls = 0

    def is_retry_safe(self, step) -> bool:
        del step
        return True

    async def execute(self, step, run, *, invocation_id):
        del step, run, invocation_id
        self.calls += 1
        return AgentStepResult(output=self.output)


class NoopClient:
    async def stream_message(self, request):
        raise AssertionError(f"governed tool action unexpectedly called the model: {request}")
        yield


def _write_incident_workflow(workspace: Path) -> None:
    (workspace / "automations" / "incident.yaml").write_text(
        """\
version: 1
id: incident-routing
priority: 100
source_behavior: consume
trigger:
  event: channel.message
  source:
    channel: slack
    chat_ids: [C_ALERTS]
conditions:
  path: event.payload.text
  op: contains
  value: DOWN
policy:
  allowed_actions: [channel.send, knowledge.upsert]
  allowed_tools: []
  channel_destinations:
    slack: [C_OPERATIONS]
  knowledge_namespaces: [incidents]
steps:
  - id: assess
    type: agent
    skill: incident-triage
    allowed_tools: []
    output_schema:
      summary: {type: string}
      knowledge: {type: string}
  - id: notify
    type: action
    action: channel.send
    with:
      channel: slack
      chat_id: C_OPERATIONS
      content: '${steps.assess.output.summary}'
  - id: remember
    type: action
    action: knowledge.upsert
    with:
      namespace: incidents
      title: '${steps.assess.output.summary}'
      content: '${steps.assess.output.knowledge}'
""",
        encoding="utf-8",
    )


def _write_approval_workflow(workspace: Path) -> None:
    (workspace / "automations" / "approval.yaml").write_text(
        """\
version: 1
id: approval-routing
source_behavior: consume
trigger:
  event: channel.message
  source: {channel: slack, chat_ids: [C_REQUESTS]}
policy:
  allowed_actions: [channel.send]
  channel_destinations: {slack: [C_OPERATIONS]}
steps:
  - id: approve
    type: approval
    prompt: Approve routing this request?
    approver_ids: [U_APPROVER]
    expires_seconds: 900
  - id: notify
    type: action
    action: channel.send
    with:
      channel: slack
      chat_id: C_OPERATIONS
      content: Request approved
""",
        encoding="utf-8",
    )


def test_channel_message_event_sanitizes_slack_metadata_and_signed_media() -> None:
    message = InboundMessage(
        channel="slack",
        sender_id="U1",
        chat_id="C1",
        content="Production is DOWN",
        timestamp=datetime(2026, 7, 5, 12, 0),
        media=["https://files.example/report.txt?token=secret"],
        metadata={
            "chat_type": "group",
            "slack": {
                "thread_ts": "171.1",
                "channel_type": "channel",
                "event": {
                    "type": "message",
                    "ts": "171.2",
                    "authorization": "must-not-persist",
                },
            },
        },
    )

    event = channel_message_event(message)

    assert event.id == "slack:171.2"
    assert event.occurred_at.tzinfo is not None
    assert event.subject.thread_id == "171.1"
    assert event.subject.message_id == "171.2"
    assert event.payload["attachments"] == [{"name": "report.txt", "kind": "https"}]
    assert "authorization" not in str(event.model_dump(mode="json"))


def test_channel_message_event_deduplicates_round_tripped_ancestry() -> None:
    message = InboundMessage(
        channel="slack",
        sender_id="U1",
        chat_id="C1",
        content="looped message",
        timestamp=datetime(2026, 7, 5, 12, 0),
        metadata={
            "event_id": "event-2",
            "_automation": {
                "generated": True,
                "ancestry": ["event-1", "run-1", "event-1", "run-1"],
            },
        },
    )

    event = channel_message_event(message)

    assert event.automation_generated is True
    assert event.ancestry == ["event-1", "run-1"]


@pytest.mark.asyncio
async def test_service_runs_slack_event_to_cross_channel_message_and_memory(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    bus = MessageBus()
    agent = StaticAgent(
        {
            "summary": "Production unavailable",
            "knowledge": "The production endpoint failed its health check.",
        }
    )
    service = OhmoAutomationService(
        workspace=workspace,
        cwd=tmp_path,
        bus=bus,
        agent_executor=agent,
    )
    _write_incident_workflow(workspace)
    await service.start()
    message = InboundMessage(
        channel="slack",
        sender_id="U1",
        chat_id="C_ALERTS",
        content="Production is DOWN",
        metadata={"slack": {"event": {"type": "message", "ts": "171.2"}}},
    )

    dispatch = await service.dispatch_message(message)
    await service.drain()

    assert dispatch.source_behavior == "consume"
    assert dispatch.workflow_ids == ("incident-routing",)
    assert len(dispatch.created_run_ids) == 1
    outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
    assert outbound.channel == "slack"
    assert outbound.chat_id == "C_OPERATIONS"
    assert outbound.content == "Production unavailable"
    assert outbound.metadata["_automation"]["generated"] is True
    memory_files = [
        path for path in (workspace / "memory").glob("*.md") if path.name != "MEMORY.md"
    ]
    assert len(memory_files) == 1
    metadata, body, _, _ = split_memory_file(memory_files[0].read_text(encoding="utf-8"))
    assert metadata["namespace"] == "incidents"
    assert metadata["source"] == "automation:incident-routing"
    assert "production endpoint failed" in body
    completed = service.store.load_run(dispatch.run_ids[0])
    assert completed.steps[-1].attempts[0].retry_safe is True

    duplicate = await service.dispatch_message(message)
    await service.drain()
    assert duplicate.created_run_ids == ()
    assert agent.calls == 1
    assert bus.outbound_size == 0
    await service.stop()


@pytest.mark.asyncio
async def test_service_resumes_reserved_pending_run_on_startup(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bus = MessageBus()
    first_agent = StaticAgent({"summary": "unused", "knowledge": "unused"})
    first = OhmoAutomationService(
        workspace=workspace,
        cwd=tmp_path,
        bus=bus,
        agent_executor=first_agent,
    )
    _write_incident_workflow(workspace)
    await first.start()
    event = channel_message_event(
        InboundMessage(
            channel="slack",
            sender_id="U1",
            chat_id="C_ALERTS",
            content="Production is DOWN",
            metadata={"slack": {"event": {"ts": "pending-1"}}},
        )
    )
    reservation = await first.runner.submit(first.definitions[0], event)
    assert reservation.run.status == "pending"
    await first.stop()

    resumed_agent = StaticAgent(
        {"summary": "Recovered incident", "knowledge": "Recovered after restart."}
    )
    resumed = OhmoAutomationService(
        workspace=workspace,
        cwd=tmp_path,
        bus=bus,
        agent_executor=resumed_agent,
    )
    await resumed.start()
    await resumed.drain()

    assert resumed_agent.calls == 1
    assert resumed.store.load_run(reservation.run.id).status == "completed"
    assert (await bus.consume_outbound()).content == "Recovered incident"
    await resumed.stop()


@pytest.mark.asyncio
async def test_targeted_submission_does_not_resume_unrelated_pending_runs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bus = MessageBus()
    agent = StaticAgent(
        {"summary": "Target run", "knowledge": "Only the submitted event ran."}
    )
    service = OhmoAutomationService(
        workspace=workspace,
        cwd=tmp_path,
        bus=bus,
        agent_executor=agent,
    )
    _write_incident_workflow(workspace)
    await service.validate_configuration()
    definition = service.definitions[0]
    first_event = channel_message_event(
        InboundMessage(
            channel="slack",
            sender_id="U1",
            chat_id="C_ALERTS",
            content="Production is DOWN",
            metadata={"slack": {"event": {"ts": "pending-target-1"}}},
        )
    )
    pending = await service.runner.submit(definition, first_event)
    second_event = first_event.model_copy(update={"id": "slack:pending-target-2"})

    dispatch = await service.submit_workflow(
        definition.id,
        second_event,
        resume_existing_runs=False,
    )
    await service.drain()

    assert service.store.load_run(pending.run.id).status == "pending"
    assert service.store.load_run(dispatch.run_ids[0]).status == "completed"
    assert agent.calls == 1
    await service.stop()


@pytest.mark.asyncio
async def test_service_rejects_definition_with_unknown_action(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bus = MessageBus()
    service = OhmoAutomationService(
        workspace=workspace,
        cwd=tmp_path,
        bus=bus,
        agent_executor=StaticAgent({}),
    )
    (workspace / "automations" / "unknown.yaml").write_text(
        """\
version: 1
id: unknown-action
trigger: {event: channel.message}
policy: {allowed_actions: [custom.missing]}
steps:
  - id: missing
    type: action
    action: custom.missing
    with: {}
""",
        encoding="utf-8",
    )

    await service.start()

    assert service.definitions == ()
    assert "unknown automation actions: custom.missing" in service.diagnostics[0].message
    await service.stop()


@pytest.mark.asyncio
async def test_service_executes_tool_action_through_runtime_governance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    source = tmp_path / "source.txt"
    source.write_text("governed content\n", encoding="utf-8")
    (workspace / "automations").mkdir(parents=True)
    (workspace / "automations" / "tool.yaml").write_text(
        f"""\
version: 1
id: governed-read
trigger:
  event: channel.message
  source: {{channel: slack, chat_ids: [C_TOOLS]}}
policy:
  allowed_actions: [tool.execute]
  allowed_tools: [read_file]
steps:
  - id: inspect
    type: action
    action: tool.execute
    with:
      tool: read_file
      input: {{path: {source!s}}}
""",
        encoding="utf-8",
    )
    service = OhmoAutomationService(
        workspace=workspace,
        cwd=tmp_path,
        bus=MessageBus(),
        agent_executor=StaticAgent({}),
        tool_api_client=NoopClient(),
    )

    await service.start()
    dispatch = await service.dispatch_message(
        InboundMessage(
            channel="slack",
            sender_id="U1",
            chat_id="C_TOOLS",
            content="inspect",
            metadata={"slack": {"event": {"ts": "tool-action-1"}}},
        )
    )
    await service.drain()

    run = service.store.load_run(dispatch.run_ids[0])
    assert run.status == "completed"
    assert "governed content" in run.steps[0].output["content"]
    assert run.steps[0].attempts[0].retry_safe is True
    await service.stop()


@pytest.mark.asyncio
async def test_targeted_retry_restores_stored_tool_capabilities_and_adds_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "workspace"
    source = tmp_path / "created-after-failure.txt"
    (workspace / "automations").mkdir(parents=True)
    (workspace / "automations" / "tool.yaml").write_text(
        f"""\
version: 1
id: retry-governed-read
trigger:
  event: channel.message
  source: {{channel: slack, chat_ids: [C_TOOLS]}}
policy:
  allowed_actions: [tool.execute]
  allowed_tools: [read_file]
steps:
  - id: inspect
    type: action
    action: tool.execute
    with:
      tool: read_file
      input: {{path: {source!s}}}
""",
        encoding="utf-8",
    )
    first = OhmoAutomationService(
        workspace=workspace,
        cwd=tmp_path,
        bus=MessageBus(),
        agent_executor=StaticAgent({}),
        tool_api_client=NoopClient(),
    )
    await first.start()
    dispatch = await first.dispatch_message(
        InboundMessage(
            channel="slack",
            sender_id="U1",
            chat_id="C_TOOLS",
            content="inspect",
            metadata={"slack": {"event": {"ts": "tool-retry-1"}}},
        )
    )
    await first.drain()
    failed = first.store.load_run(dispatch.run_ids[0])
    assert failed.status == "failed"
    await first.stop()

    source.write_text("available now\n", encoding="utf-8")
    second = OhmoAutomationService(
        workspace=workspace,
        cwd=tmp_path,
        bus=MessageBus(),
        agent_executor=StaticAgent({}),
        tool_api_client=NoopClient(),
    )
    await second.retry_run(failed.id)
    await second.drain()

    completed = second.store.load_run(failed.id)
    assert completed.status == "completed"
    assert len(completed.steps[0].attempts) == 2
    assert "available now" in completed.steps[0].output["content"]
    await second.stop()


@pytest.mark.asyncio
async def test_service_rejects_tool_workflow_with_unavailable_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    workspace = tmp_path / "workspace"
    (workspace / "automations").mkdir(parents=True)
    (workspace / "automations" / "tool.yaml").write_text(
        """\
version: 1
id: missing-tool
trigger: {event: manual.tool}
policy:
  allowed_actions: [tool.execute]
  allowed_tools: [missing_tool]
steps:
  - id: call
    type: action
    action: tool.execute
    with: {tool: missing_tool, input: {}}
""",
        encoding="utf-8",
    )
    service = OhmoAutomationService(
        workspace=workspace,
        cwd=tmp_path,
        bus=MessageBus(),
        agent_executor=StaticAgent({}),
        tool_api_client=NoopClient(),
    )

    await service.start()

    assert service.definitions == ()
    assert "unavailable tools: missing_tool" in service.diagnostics[0].message
    await service.stop()


@pytest.mark.asyncio
async def test_service_delivers_and_authenticates_durable_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bus = MessageBus()
    service = OhmoAutomationService(
        workspace=workspace,
        cwd=tmp_path,
        bus=bus,
        agent_executor=StaticAgent({}),
    )
    _write_approval_workflow(workspace)
    await service.start()
    source = InboundMessage(
        channel="slack",
        sender_id="U_REQUESTER",
        chat_id="C_REQUESTS",
        content="please route",
        metadata={"slack": {"event": {"ts": "approval-1"}}},
    )

    dispatch = await service.dispatch_message(source)
    await service.drain()

    request = await bus.consume_outbound()
    assert request.chat_id == "C_REQUESTS"
    assert f"/automation approve {dispatch.run_ids[0]}" in request.content
    waiting = service.store.load_run(dispatch.run_ids[0])
    assert waiting.status == "waiting_approval"
    assert waiting.approvals[-1].notification_sent_at is not None
    assert service.status_counts()["waiting"] == 1

    denied = await service.handle_gateway_command(
        InboundMessage(
            channel="slack",
            sender_id="U_ATTACKER",
            chat_id="C_REQUESTS",
            content=f"/automation approve {waiting.id}",
        )
    )
    assert denied is not None and "not allowed to approve" in denied
    assert service.store.load_run(waiting.id).status == "waiting_approval"

    approved = await service.handle_gateway_command(
        InboundMessage(
            channel="slack",
            sender_id="U_APPROVER",
            chat_id="C_REQUESTS",
            content=f"/automation approve {waiting.id}",
        )
    )
    assert approved == f"Automation run {waiting.id} approved."
    await service.drain()
    notification = await bus.consume_outbound()
    assert notification.chat_id == "C_OPERATIONS"
    assert notification.content == "Request approved"
    assert service.store.load_run(waiting.id).status == "completed"
    await service.stop()


@pytest.mark.asyncio
async def test_service_does_not_redeliver_recorded_approval_after_restart(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    first_bus = MessageBus()
    first = OhmoAutomationService(
        workspace=workspace,
        cwd=tmp_path,
        bus=first_bus,
        agent_executor=StaticAgent({}),
    )
    _write_approval_workflow(workspace)
    await first.start()
    dispatch = await first.dispatch_message(
        InboundMessage(
            channel="slack",
            sender_id="U_REQUESTER",
            chat_id="C_REQUESTS",
            content="please route",
            metadata={"slack": {"event": {"ts": "approval-restart"}}},
        )
    )
    await first.drain()
    await first_bus.consume_outbound()
    await first.stop()

    second_bus = MessageBus()
    second = OhmoAutomationService(
        workspace=workspace,
        cwd=tmp_path,
        bus=second_bus,
        agent_executor=StaticAgent({}),
    )
    await second.start()
    await second.drain()

    assert second.store.load_run(dispatch.run_ids[0]).status == "waiting_approval"
    assert second_bus.outbound_size == 0
    await second.stop()


def test_namespaced_memory_upsert_reuses_identity_and_path(tmp_path: Path) -> None:
    first = add_memory_entry(
        tmp_path,
        "Incident 42",
        "Initial finding",
        namespace="incidents",
        source="automation:test",
    )
    first_metadata, _, _, _ = split_memory_file(first.read_text(encoding="utf-8"))

    second = add_memory_entry(
        tmp_path,
        "Incident 42",
        "Corrected finding",
        namespace="incidents",
        source="automation:test",
    )
    second_metadata, body, _, _ = split_memory_file(second.read_text(encoding="utf-8"))

    assert second == first
    assert second_metadata["id"] == first_metadata["id"]
    assert body.strip() == "Corrected finding"

    separate = add_memory_entry(
        tmp_path,
        "Incident 43",
        "Corrected finding",
        namespace="incidents",
        source="automation:test",
    )
    assert separate != first

    with pytest.raises(ValueError, match="lowercase identifier"):
        add_memory_entry(
            tmp_path,
            "Unsafe",
            "content",
            namespace="../outside",
        )


def test_manual_memory_keeps_legacy_append_semantics_for_repeated_title(tmp_path: Path) -> None:
    first = add_memory_entry(tmp_path, "Preference", "First value")
    second = add_memory_entry(tmp_path, "Preference", "Second value")

    assert second != first
    assert first.read_text(encoding="utf-8") != second.read_text(encoding="utf-8")


def test_channel_media_is_confined_to_ohmo_attachments(tmp_path: Path) -> None:
    attachments = tmp_path / "attachments"
    attachments.mkdir()
    allowed = attachments / "report.txt"
    allowed.write_text("safe", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("private", encoding="utf-8")

    assert _resolve_media_paths([str(allowed)], attachments) == [str(allowed.resolve())]
    with pytest.raises(ValueError, match="attachments directory"):
        _resolve_media_paths([str(outside)], attachments)


@pytest.mark.asyncio
async def test_gateway_bridge_skips_normal_assistant_for_consumed_message() -> None:
    bus = MessageBus()
    dispatched = asyncio.Event()

    class AutomationService:
        async def dispatch_message(self, message):
            del message
            dispatched.set()
            return AutomationDispatch(
                source_behavior="consume",
                workflow_ids=("route",),
                run_ids=("run-automation-0001",),
            )

    class RuntimePool:
        calls = 0

        async def stream_message(self, message, session_key):
            del message, session_key
            self.calls += 1
            if False:
                yield None

    runtime_pool = RuntimePool()
    bridge = OhmoGatewayBridge(
        bus=bus,
        runtime_pool=runtime_pool,
        automation_service=AutomationService(),
    )
    task = asyncio.create_task(bridge.run())
    try:
        await bus.publish_inbound(
            InboundMessage(
                channel="slack",
                sender_id="U1",
                chat_id="C1",
                content="route this",
            )
        )
        await asyncio.wait_for(dispatched.wait(), timeout=1)
        await asyncio.sleep(0)
        assert runtime_pool.calls == 0
    finally:
        bridge.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_gateway_bridge_routes_approval_command_before_normal_dispatch() -> None:
    bus = MessageBus()
    handled = asyncio.Event()

    class AutomationService:
        async def handle_gateway_command(self, message):
            assert message.sender_id == "U_APPROVER"
            handled.set()
            return "Automation run approved."

        async def dispatch_message(self, message):
            raise AssertionError(f"approval command was dispatched as an event: {message}")

    class RuntimePool:
        async def stream_message(self, message, session_key):
            raise AssertionError((message, session_key))
            yield

    bridge = OhmoGatewayBridge(
        bus=bus,
        runtime_pool=RuntimePool(),
        automation_service=AutomationService(),
    )
    task = asyncio.create_task(bridge.run())
    try:
        await bus.publish_inbound(
            InboundMessage(
                channel="slack",
                sender_id="U_APPROVER",
                chat_id="C_REQUESTS",
                content="/automation approve run-automation-0001",
            )
        )
        await asyncio.wait_for(handled.wait(), timeout=1)
        reply = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
        assert reply.content == "Automation run approved."
    finally:
        bridge.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_gateway_bridge_handles_stop_before_generic_automation() -> None:
    bus = MessageBus()
    dispatched = asyncio.Event()

    class AutomationService:
        async def handle_gateway_command(self, message):
            raise AssertionError(f"legacy control command reached automation: {message}")

        async def dispatch_message(self, message):
            del message
            dispatched.set()
            return AutomationDispatch(source_behavior="consume")

    class RuntimePool:
        async def stream_message(self, message, session_key):
            raise AssertionError((message, session_key))
            yield

    bridge = OhmoGatewayBridge(
        bus=bus,
        runtime_pool=RuntimePool(),
        automation_service=AutomationService(),
    )
    task = asyncio.create_task(bridge.run())
    try:
        await bus.publish_inbound(
            InboundMessage(
                channel="slack",
                sender_id="U1",
                chat_id="C1",
                content="/stop",
            )
        )
        reply = await asyncio.wait_for(bus.consume_outbound(), timeout=1)
        assert reply.content == "当前没有正在运行的任务。"
        assert dispatched.is_set() is False
    finally:
        bridge.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
