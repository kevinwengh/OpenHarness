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

    with pytest.raises(ValueError, match="lowercase identifier"):
        add_memory_entry(
            tmp_path,
            "Unsafe",
            "content",
            namespace="../outside",
        )


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
