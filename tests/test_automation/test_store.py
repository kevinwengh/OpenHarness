from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from openharness.automation.state import RunError, TransitionError, WorkflowRun
from openharness.automation.store import AutomationStore, AutomationStoreError

from .conftest import workflow_payload
from openharness.automation.models import WorkflowDefinition


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 5, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


@pytest.fixture
def store(tmp_path) -> AutomationStore:
    ids = iter(["run-20260705T000000000000Z-aaaaaaaaaaaa", "run-20260705T000001000000Z-bbbbbbbbbbbb"])
    return AutomationStore(tmp_path / "automation", clock=Clock(), id_factory=lambda: next(ids))


def test_reserve_is_idempotent_and_preserves_definition_snapshot(store, workflow, channel_event) -> None:
    first = store.reserve(workflow, channel_event, concurrency_key="slack:C_ALERTS")
    second = store.reserve(workflow, channel_event, concurrency_key="different")

    assert first.created is True
    assert second.created is False
    assert second.run.id == first.run.id
    assert second.run.concurrency_key == "slack:C_ALERTS"
    assert store.index_path.exists()
    assert store.load_run(first.run.id) == first.run


def test_concurrent_reservations_create_one_run(tmp_path, workflow, channel_event) -> None:
    root = tmp_path / "automation"

    def reserve():
        return AutomationStore(root).reserve(workflow, channel_event)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: reserve(), range(2)))

    assert sorted(result.created for result in results) == [False, True]
    assert len({result.run.id for result in results}) == 1
    assert len(list((root / "runs").glob("run-*.json"))) == 1


def test_run_id_collision_fails_without_overwriting_existing_run(
    tmp_path,
    workflow,
    channel_event,
) -> None:
    root = tmp_path / "automation"
    run_id = "run-20260705T000000000000Z-aaaaaaaaaaaa"
    store = AutomationStore(root, id_factory=lambda: run_id)
    first = store.reserve(workflow, channel_event).run

    with pytest.raises(AutomationStoreError, match="unique workflow run ID"):
        store.reserve(workflow, channel_event.model_copy(update={"id": "different-event"}))

    assert store.load_run(first.id).event.id == channel_event.id


def test_reserve_recovers_orphan_when_index_write_was_lost(store, workflow, channel_event) -> None:
    first = store.reserve(workflow, channel_event)
    store.index_path.unlink()

    second = store.reserve(workflow, channel_event)

    assert second.created is False
    assert second.run.id == first.run.id


def test_reserve_fails_closed_when_index_points_to_corrupt_run(
    store,
    workflow,
    channel_event,
) -> None:
    run = store.reserve(workflow, channel_event).run
    (store.runs_dir / f"{run.id}.json").write_text("{", encoding="utf-8")

    with pytest.raises(AutomationStoreError, match="reservation points to unreadable"):
        store.reserve(workflow, channel_event)


def test_store_rejects_path_traversal(store) -> None:
    with pytest.raises(AutomationStoreError, match="invalid workflow run ID"):
        store.load_run("../../credentials")


def test_step_lifecycle_checkpoints_output_and_context(store, workflow, channel_event) -> None:
    run = store.reserve(workflow, channel_event).run
    run = store.start_step(run.id, "assess", input={"text": "down"}, retry_safe=True)
    assert run.status == "running"
    assert run.steps[0].attempts[0].logical_idempotency_key == f"{run.id}:assess"

    output = {"summary": "Production down", "customer_impact": True}
    run = store.complete_step(run.id, "assess", output=output)

    assert run.current_step == 1
    assert run.steps[0].status == "completed"
    assert run.context["steps"]["assess"]["output"] == output
    assert store.load_run(run.id) == run

    run = store.start_step(run.id, "notify", retry_safe=False)
    run = store.complete_step(run.id, "notify", output={"message_id": "M2"})
    run = store.transition_run(run.id, "completed")
    assert run.status == "completed"


def test_illegal_or_out_of_order_step_transition_is_rejected(store, workflow, channel_event) -> None:
    run = store.reserve(workflow, channel_event).run
    with pytest.raises(TransitionError, match="not the current step"):
        store.start_step(run.id, "notify", retry_safe=False)
    with pytest.raises(TransitionError, match="illegal run transition"):
        store.transition_run(run.id, "completed")


def test_failed_step_requires_override_when_outcome_is_unknown(store, workflow, channel_event) -> None:
    run = store.reserve(workflow, channel_event).run
    run = store.start_step(run.id, "assess", retry_safe=False)
    error = RunError(category="network", message="connection dropped")
    run = store.fail_step(run.id, "assess", error=error, outcome_unknown=True)

    assert run.status == "failed"
    assert run.error and run.error.outcome_unknown is True
    with pytest.raises(TransitionError, match="explicit override"):
        store.retry_run(run.id)

    retried = store.retry_run(run.id, allow_unknown_outcome=True)
    assert retried.status == "pending"
    assert retried.steps[0].status == "pending"


def test_skip_and_cancel_update_current_state(store, workflow, channel_event) -> None:
    run = store.reserve(workflow, channel_event).run
    run = store.skip_step(run.id, "assess")
    assert run.current_step == 1
    assert run.steps[0].status == "skipped"

    run = store.start_step(run.id, "notify", retry_safe=False)
    run = store.cancel_run(run.id, reason="operator stopped it")
    assert run.status == "cancelled"
    assert run.steps[1].status == "failed"
    assert run.steps[1].attempts[-1].status == "outcome_unknown"


def test_approval_authorization_resolution_and_expiry(store, channel_event) -> None:
    payload = workflow_payload(source_behavior="consume")
    payload["policy"] = {}
    payload["steps"] = [
        {
            "id": "approve",
            "type": "approval",
            "prompt": "Approve escalation?",
            "approver_ids": ["U_COMMANDER"],
            "expires_seconds": 30,
        }
    ]
    definition = WorkflowDefinition.model_validate(payload)
    run = store.reserve(definition, channel_event).run
    waiting = store.wait_for_approval(run.id, "approve")
    assert waiting.status == "waiting_approval"
    assert waiting.approvals[-1].notification_sent_at is None
    notified = store.mark_approval_notified(run.id)
    assert notified.approvals[-1].notification_sent_at is not None
    assert store.mark_approval_notified(run.id) == notified

    other = store.reserve(
        definition,
        channel_event.model_copy(update={"id": "another-approval"}),
    ).run
    with pytest.raises(TransitionError, match="approval steps"):
        store.start_step(other.id, "approve", retry_safe=False)

    with pytest.raises(TransitionError, match="not allowed"):
        store.resolve_approval(run.id, actor_id="U_OTHER", approved=True)

    approved = store.resolve_approval(run.id, actor_id="U_COMMANDER", approved=True)
    assert approved.status == "pending"
    assert approved.current_step == 1
    assert approved.approvals[-1].status == "approved"


def test_cancelling_waiting_run_resolves_pending_approval(store, channel_event) -> None:
    payload = workflow_payload(source_behavior="consume")
    payload["policy"] = {}
    payload["steps"] = [
        {
            "id": "approve",
            "type": "approval",
            "prompt": "Approve escalation?",
            "approver_ids": ["U_COMMANDER"],
        }
    ]
    definition = WorkflowDefinition.model_validate(payload)
    run = store.reserve(definition, channel_event).run
    store.wait_for_approval(run.id, "approve")

    cancelled = store.cancel_run(run.id)

    assert cancelled.status == "cancelled"
    assert cancelled.approvals[-1].status == "rejected"
    assert cancelled.approvals[-1].resolved_at is not None


def test_recovery_expires_waiting_approval(tmp_path, channel_event) -> None:
    payload = workflow_payload(source_behavior="consume")
    payload["policy"] = {}
    payload["steps"] = [
        {
            "id": "approve",
            "type": "approval",
            "prompt": "Approve escalation?",
            "approver_ids": ["U_COMMANDER"],
            "expires_seconds": 1,
        }
    ]
    definition = WorkflowDefinition.model_validate(payload)
    clock = Clock()
    store = AutomationStore(
        tmp_path / "automation",
        clock=clock,
        id_factory=lambda: "run-20260705T000000000000Z-aaaaaaaaaaaa",
    )
    run = store.reserve(definition, channel_event).run
    store.wait_for_approval(run.id, "approve")

    store.recover()

    expired = store.load_run(run.id)
    assert expired.status == "failed"
    assert expired.approvals[-1].status == "expired"


def test_recovery_retries_safe_attempt_but_marks_unsafe_outcome_unknown(
    tmp_path,
    channel_event,
) -> None:
    workflow = WorkflowDefinition.model_validate(
        workflow_payload(defaults={"retry": {"attempts": 2, "backoff_seconds": [0]}})
    )
    clock = Clock()
    ids = iter(["run-20260705T000000000000Z-aaaaaaaaaaaa", "run-20260705T000001000000Z-bbbbbbbbbbbb"])
    store = AutomationStore(tmp_path / "automation", clock=clock, id_factory=lambda: next(ids))
    safe_event = channel_event.model_copy(update={"id": "safe-event"})
    unsafe_event = channel_event.model_copy(update={"id": "unsafe-event"})
    safe = store.reserve(workflow, safe_event).run
    unsafe = store.reserve(workflow, unsafe_event).run
    store.start_step(safe.id, "assess", retry_safe=True)
    store.start_step(unsafe.id, "assess", retry_safe=False)

    result = store.recover()

    assert result.recovered_run_ids == (safe.id,)
    assert result.outcome_unknown_run_ids == (unsafe.id,)
    assert store.load_run(safe.id).steps[0].status == "pending"
    assert store.load_run(unsafe.id).error.outcome_unknown is True


def test_recovery_fails_retry_safe_step_when_attempts_are_exhausted(
    store,
    workflow,
    channel_event,
) -> None:
    run = store.reserve(workflow, channel_event).run
    store.start_step(run.id, "assess", retry_safe=True)

    result = store.recover()

    failed = store.load_run(run.id)
    assert failed.status == "failed"
    assert failed.error.category == "retry_exhausted"
    assert any("attempts exhausted" in item for item in result.diagnostics)


def test_rebuild_index_skips_malformed_runs_and_restores_reservations(
    store,
    workflow,
    channel_event,
) -> None:
    run = store.reserve(workflow, channel_event).run
    (store.runs_dir / "run-malformed.json").write_text("{", encoding="utf-8")
    store.index_path.write_text("not-json", encoding="utf-8")

    result = store.rebuild_index()

    assert any("run-malformed.json" in item for item in result.diagnostics)
    index = json.loads(store.index_path.read_text(encoding="utf-8"))
    assert index["runs"][run.id]["status"] == "pending"


def test_list_runs_filters_and_orders_newest_first(store, workflow, channel_event) -> None:
    first = store.reserve(workflow, channel_event.model_copy(update={"id": "event-one"})).run
    second = store.reserve(workflow, channel_event.model_copy(update={"id": "event-two"})).run
    store.cancel_run(second.id)

    assert [run.id for run in store.list_runs()] == [second.id, first.id]
    assert [run.id for run in store.list_runs(status="cancelled")] == [second.id]


def test_run_model_rejects_out_of_order_or_inconsistent_active_state(
    store,
    workflow,
    channel_event,
) -> None:
    run = store.reserve(workflow, channel_event).run
    raw = run.model_dump(mode="python")
    raw["current_step"] = 1
    with pytest.raises(ValueError, match="first unfinished"):
        WorkflowRun.model_validate(raw)


def test_store_rejects_run_larger_than_persisted_bound(
    tmp_path,
    workflow,
    channel_event,
    monkeypatch,
) -> None:
    monkeypatch.setattr("openharness.automation.store.MAX_RUN_BYTES", 100)
    store = AutomationStore(tmp_path / "automation")
    with pytest.raises(AutomationStoreError, match="exceeds 100 bytes"):
        store.reserve(workflow, channel_event)
    assert list(store.runs_dir.glob("run-*.json")) == []


def test_store_rejects_oversized_run_on_read(store, monkeypatch) -> None:
    monkeypatch.setattr("openharness.automation.store.MAX_RUN_BYTES", 10)
    path = store.runs_dir / "run-oversized.json"
    path.write_text("x" * 11, encoding="utf-8")
    with pytest.raises(AutomationStoreError, match="exceeds 10 bytes"):
        store.load_run("run-oversized")
