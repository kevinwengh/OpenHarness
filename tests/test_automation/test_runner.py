from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path

import pytest
from pydantic import BaseModel

from openharness.automation.actions import (
    ActionExecutionContext,
    ActionRegistry,
    ActionResult,
    AutomationAction,
)
from openharness.automation.models import AgentStep, WorkflowDefinition
from openharness.automation.runner import (
    AgentStepResult,
    WorkflowNotMatchedError,
    WorkflowRunner,
)
from openharness.automation.store import AutomationStore

from .conftest import workflow_payload


class RecordInput(BaseModel):
    message: str


class RecordingAction(AutomationAction):
    name = "record"
    description = "Record test action inputs."
    input_model = RecordInput

    def __init__(
        self,
        results: list[ActionResult] | None = None,
        *,
        retry_safe: bool = False,
    ) -> None:
        self.results = deque(results or [ActionResult(output={"message": "ok"})])
        self.retry_safe = retry_safe
        self.calls: list[tuple[RecordInput, ActionExecutionContext]] = []

    def is_retry_safe(self, arguments: RecordInput) -> bool:
        del arguments
        return self.retry_safe

    async def execute(
        self,
        arguments: RecordInput,
        context: ActionExecutionContext,
    ) -> ActionResult:
        self.calls.append((arguments, context))
        return self.results.popleft()


class FakeAgent:
    def __init__(self, results: list[AgentStepResult], *, retry_safe: bool = True) -> None:
        self.results = deque(results)
        self.retry_safe = retry_safe
        self.calls: list[tuple[AgentStep, str]] = []

    def is_retry_safe(self, step: AgentStep) -> bool:
        del step
        return self.retry_safe

    async def execute(self, step, run, *, invocation_id):
        del run
        self.calls.append((step, invocation_id))
        return self.results.popleft()


def action_definition(*, steps, **overrides) -> WorkflowDefinition:
    payload = workflow_payload()
    payload["policy"] = {"allowed_actions": ["record"]}
    payload["steps"] = steps
    payload.update(overrides)
    return WorkflowDefinition.model_validate(payload)


def runner_for(
    tmp_path: Path,
    action: RecordingAction,
    *,
    agent=None,
    sleeper=asyncio.sleep,
) -> WorkflowRunner:
    registry = ActionRegistry()
    registry.register(action)
    return WorkflowRunner(
        store=AutomationStore(tmp_path / "automation"),
        actions=registry,
        agent_executor=agent,
        sleeper=sleeper,
    )


@pytest.mark.asyncio
async def test_runner_executes_sequential_actions_with_typed_template_output(
    tmp_path,
    channel_event,
) -> None:
    action = RecordingAction(
        [
            ActionResult(output={"summary": "Production down"}),
            ActionResult(output={"sent": True}),
        ]
    )
    definition = action_definition(
        steps=[
            {"id": "classify", "type": "action", "action": "record", "with": {"message": "${event.payload.text}"}},
            {"id": "notify", "type": "action", "action": "record", "with": {"message": "${steps.classify.output.summary}"}},
        ]
    )

    result = await runner_for(tmp_path, action).run_event(definition, channel_event)

    assert result.run.status == "completed"
    assert [call[0].message for call in action.calls] == ["Production is DOWN", "Production down"]
    assert action.calls[0][1].logical_idempotency_key.endswith(":classify")
    assert result.run.steps[1].output == {"sent": True}


@pytest.mark.asyncio
async def test_runner_skips_false_condition_without_calling_action(tmp_path, channel_event) -> None:
    action = RecordingAction()
    definition = action_definition(
        steps=[
            {
                "id": "skip",
                "type": "action",
                "action": "record",
                "with": {"message": "ignored"},
                "when": {"path": "event.payload.severity", "op": "lt", "value": 2},
            }
        ]
    )

    result = await runner_for(tmp_path, action).run_event(definition, channel_event)

    assert result.run.status == "completed"
    assert result.run.steps[0].status == "skipped"
    assert action.calls == []


@pytest.mark.asyncio
async def test_runner_retries_only_retryable_safe_action(tmp_path, channel_event) -> None:
    action = RecordingAction(
        [
            ActionResult(
                is_error=True,
                error_category="temporary",
                error_message="try again",
                retryable=True,
            ),
            ActionResult(output={"sent": True}),
        ],
        retry_safe=True,
    )
    definition = action_definition(
        defaults={"retry": {"attempts": 2, "backoff_seconds": [7]}},
        steps=[{"id": "notify", "type": "action", "action": "record", "with": {"message": "hello"}}],
    )
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    result = await runner_for(tmp_path, action, sleeper=sleep).run_event(definition, channel_event)

    assert result.run.status == "completed"
    assert len(result.run.steps[0].attempts) == 2
    assert delays == [7]


@pytest.mark.asyncio
async def test_runner_does_not_retry_error_when_action_is_not_retry_safe(
    tmp_path,
    channel_event,
) -> None:
    action = RecordingAction(
        [
            ActionResult(
                is_error=True,
                error_category="temporary",
                error_message="claimed retry",
                retryable=True,
            ),
            ActionResult(output={"should_not_run": True}),
        ],
        retry_safe=False,
    )
    definition = action_definition(
        defaults={"retry": {"attempts": 2, "backoff_seconds": [0]}},
        steps=[{"id": "notify", "type": "action", "action": "record", "with": {"message": "hello"}}],
    )

    result = await runner_for(tmp_path, action).run_event(definition, channel_event)

    assert result.run.status == "failed"
    assert len(action.calls) == 1


@pytest.mark.asyncio
async def test_runner_marks_unsafe_action_exception_outcome_unknown(tmp_path, channel_event) -> None:
    class RaisingAction(RecordingAction):
        async def execute(self, arguments, context):
            del arguments, context
            raise RuntimeError("connection vanished")

    action = RaisingAction(retry_safe=False)
    definition = action_definition(
        steps=[{"id": "notify", "type": "action", "action": "record", "with": {"message": "hello"}}]
    )

    result = await runner_for(tmp_path, action).run_event(definition, channel_event)

    assert result.run.status == "failed"
    assert result.run.error.outcome_unknown is True
    assert result.run.steps[0].attempts[0].status == "outcome_unknown"


@pytest.mark.asyncio
async def test_cancelling_unsafe_running_action_records_unknown_outcome(
    tmp_path,
    channel_event,
) -> None:
    entered = asyncio.Event()

    class BlockingAction(RecordingAction):
        async def execute(self, arguments, context):
            del arguments, context
            entered.set()
            await asyncio.Event().wait()

    action = BlockingAction(retry_safe=False)
    definition = action_definition(
        steps=[{"id": "notify", "type": "action", "action": "record", "with": {"message": "hello"}}]
    )
    runner = runner_for(tmp_path, action)
    reservation = await runner.submit(definition, channel_event)
    task = asyncio.create_task(runner.execute(reservation.run.id))
    await entered.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    cancelled = runner.store.load_run(reservation.run.id)
    assert cancelled.status == "cancelled"
    assert cancelled.error.outcome_unknown is True
    assert cancelled.steps[0].attempts[-1].status == "outcome_unknown"


@pytest.mark.asyncio
async def test_runner_can_leave_interrupted_run_for_startup_recovery(
    tmp_path,
    channel_event,
) -> None:
    started = asyncio.Event()

    class BlockingAction(RecordingAction):
        async def execute(self, arguments, context):
            del arguments, context
            started.set()
            await asyncio.Future()

    action = BlockingAction(retry_safe=True)
    definition = action_definition(
        steps=[
            {
                "id": "hold",
                "type": "action",
                "action": "record",
                "with": {"message": "x"},
                "retry": {"attempts": 2},
            }
        ]
    )
    store = AutomationStore(tmp_path / "automation")
    registry = ActionRegistry()
    registry.register(action)
    runner = WorkflowRunner(
        store=store,
        actions=registry,
        cancel_on_task_cancel=False,
    )
    reservation = await runner.submit(definition, channel_event)
    task = asyncio.create_task(runner.execute(reservation.run.id))
    await started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert store.load_run(reservation.run.id).status == "running"
    recovery = store.recover()
    assert recovery.recovered_run_ids == (reservation.run.id,)
    assert store.load_run(reservation.run.id).status == "pending"


@pytest.mark.asyncio
async def test_runner_fails_missing_template_before_action_attempt(tmp_path, channel_event) -> None:
    action = RecordingAction()
    definition = action_definition(
        steps=[
            {"id": "notify", "type": "action", "action": "record", "with": {"message": "${event.payload.missing}"}}
        ]
    )

    result = await runner_for(tmp_path, action).run_event(definition, channel_event)

    assert result.run.status == "failed"
    assert result.run.steps[0].attempts == []
    assert result.run.error.category == "action_validation"
    assert action.calls == []


@pytest.mark.asyncio
async def test_runner_waits_for_rendered_approval(tmp_path, channel_event) -> None:
    action = RecordingAction()
    definition = action_definition(
        steps=[
            {
                "id": "approve",
                "type": "approval",
                "prompt": "Approve ${event.payload.text}?",
                "approver_ids": ["U_COMMANDER"],
            }
        ]
    )

    result = await runner_for(tmp_path, action).run_event(definition, channel_event)

    assert result.run.status == "waiting_approval"
    assert result.run.approvals[-1].prompt == "Approve Production is DOWN?"


@pytest.mark.asyncio
async def test_duplicate_event_returns_existing_run_without_repeating_actions(
    tmp_path,
    channel_event,
) -> None:
    action = RecordingAction()
    definition = action_definition(
        steps=[{"id": "notify", "type": "action", "action": "record", "with": {"message": "hello"}}]
    )
    runner = runner_for(tmp_path, action)

    first = await runner.run_event(definition, channel_event)
    second = await runner.run_event(definition, channel_event)

    assert first.created is True
    assert second.created is False
    assert second.run.id == first.run.id
    assert len(action.calls) == 1


@pytest.mark.asyncio
async def test_same_run_cannot_execute_concurrently(tmp_path, channel_event) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingSuccessfulAction(RecordingAction):
        async def execute(self, arguments, context):
            self.calls.append((arguments, context))
            entered.set()
            await release.wait()
            return ActionResult(output={"sent": True})

    action = BlockingSuccessfulAction()
    definition = action_definition(
        steps=[{"id": "notify", "type": "action", "action": "record", "with": {"message": "hello"}}]
    )
    runner = runner_for(tmp_path, action)
    reservation = await runner.submit(definition, channel_event)
    first = asyncio.create_task(runner.execute(reservation.run.id))
    await entered.wait()
    second = asyncio.create_task(runner.execute(reservation.run.id))
    await asyncio.sleep(0)
    assert len(action.calls) == 1
    release.set()

    first_result, second_result = await asyncio.gather(first, second)

    assert first_result.status == "completed"
    assert second_result.status == "completed"
    assert len(action.calls) == 1


@pytest.mark.asyncio
async def test_fake_agent_output_is_validated_and_available_to_later_action(
    tmp_path,
    channel_event,
) -> None:
    action = RecordingAction([ActionResult(output={"sent": True})])
    agent = FakeAgent(
        [AgentStepResult(output={"summary": "Investigated", "customer_impact": True})]
    )
    payload = workflow_payload()
    payload["policy"] = {"allowed_actions": ["record"], "allowed_tools": []}
    payload["steps"][0]["allowed_tools"] = []
    payload["steps"][1] = {
        "id": "notify",
        "type": "action",
        "action": "record",
        "with": {"message": "${steps.assess.output.summary}"},
    }
    definition = WorkflowDefinition.model_validate(payload)

    result = await runner_for(tmp_path, action, agent=agent).run_event(definition, channel_event)

    assert result.run.status == "completed"
    assert action.calls[0][0].message == "Investigated"
    assert len(agent.calls) == 1


@pytest.mark.asyncio
async def test_invalid_agent_output_fails_without_running_later_steps(tmp_path, channel_event) -> None:
    action = RecordingAction()
    agent = FakeAgent([AgentStepResult(output={"summary": 42, "customer_impact": True})])
    payload = workflow_payload()
    payload["policy"] = {"allowed_actions": ["record"], "allowed_tools": []}
    payload["steps"][0]["allowed_tools"] = []
    payload["steps"][1] = {
        "id": "notify",
        "type": "action",
        "action": "record",
        "with": {"message": "later"},
    }
    definition = WorkflowDefinition.model_validate(payload)

    result = await runner_for(tmp_path, action, agent=agent).run_event(definition, channel_event)

    assert result.run.status == "failed"
    assert result.run.error.category == "invalid_agent_output"
    assert action.calls == []


@pytest.mark.asyncio
async def test_non_finite_agent_output_is_rejected(tmp_path, channel_event) -> None:
    action = RecordingAction()

    class InvalidAgent(FakeAgent):
        def __init__(self) -> None:
            super().__init__([])

        async def execute(self, step, run, *, invocation_id):
            del step, run, invocation_id
            return AgentStepResult(
                output={"summary": "bad", "customer_impact": float("nan")}
            )

    agent = InvalidAgent()
    payload = workflow_payload()
    payload["policy"] = {"allowed_actions": ["record"], "allowed_tools": []}
    payload["steps"][0]["allowed_tools"] = []
    payload["steps"] = [payload["steps"][0]]
    definition = WorkflowDefinition.model_validate(payload)

    result = await runner_for(tmp_path, action, agent=agent).run_event(definition, channel_event)

    assert result.run.status == "failed"
    assert result.run.error.category == "agent_exception"
    assert "non-finite" in result.run.error.message


@pytest.mark.asyncio
async def test_oversized_action_result_becomes_failed_attempt(tmp_path, channel_event) -> None:
    class OversizedAction(RecordingAction):
        async def execute(self, arguments, context):
            del arguments, context
            return ActionResult(output={"content": "x" * 300_000})

    action = OversizedAction(retry_safe=False)
    definition = action_definition(
        steps=[{"id": "notify", "type": "action", "action": "record", "with": {"message": "hello"}}]
    )

    result = await runner_for(tmp_path, action).run_event(definition, channel_event)

    assert result.run.status == "failed"
    assert result.run.error.category == "action_exception"


@pytest.mark.asyncio
async def test_submit_rejects_nonmatching_event(tmp_path, workflow, channel_event) -> None:
    action = RecordingAction()
    event = channel_event.model_copy(
        update={"subject": channel_event.subject.model_copy(update={"chat_id": "C_OTHER"})}
    )
    with pytest.raises(WorkflowNotMatchedError):
        await runner_for(tmp_path, action).submit(workflow, event)
