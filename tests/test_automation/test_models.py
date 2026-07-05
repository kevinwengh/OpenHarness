from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from openharness.automation.models import (
    AutomationEvent,
    Condition,
    WorkflowDefinition,
    definition_revision,
)

from .conftest import workflow_payload


def test_event_requires_timezone_and_json_safe_payload() -> None:
    payload = {
        "id": "event-1",
        "type": "channel.message",
        "occurred_at": datetime(2026, 1, 1),
        "source": {"adapter": "channel"},
        "actor": {"id": "user"},
        "payload": {},
    }
    with pytest.raises(ValidationError, match="timezone"):
        AutomationEvent.model_validate(payload)

    payload["occurred_at"] = "2026-01-01T00:00:00Z"
    payload["payload"] = {"bad": object()}
    with pytest.raises(ValidationError, match="non-JSON"):
        AutomationEvent.model_validate(payload)

    payload["payload"] = {"bad": float("nan")}
    with pytest.raises(ValidationError, match="non-finite"):
        AutomationEvent.model_validate(payload)


def test_event_redacts_credential_shaped_keys_and_values_before_persistence() -> None:
    event = AutomationEvent.model_validate(
        {
            "id": "event-secret",
            "type": "manual.note",
            "occurred_at": "2026-01-01T00:00:00Z",
            "source": {"adapter": "cli"},
            "actor": {"id": "local"},
            "payload": {
                "authorization": "Bearer token-value",
                "text": "reported xoxb-1234567890-secret",
                "nested": {"accessToken": "opaque", "token": "also-opaque"},
            },
            "metadata": {"api-key": "must-not-persist"},
        }
    )

    assert event.payload["authorization"] == "[REDACTED]"
    assert event.payload["text"] == "reported [REDACTED]"
    assert event.payload["nested"] == {
        "accessToken": "[REDACTED]",
        "token": "[REDACTED]",
    }
    assert event.metadata["api-key"] == "[REDACTED]"


@pytest.mark.parametrize(
    "condition",
    [
        {"path": "payload.text", "op": "eq", "value": "x"},
        {"path": "event.payload.text", "op": "regex", "value": "(a+)+"},
        {"path": "event.payload.text", "op": "regex", "value": "a+"},
        {"path": "event.payload.text", "op": "regex", "value": "a{1,65}"},
        {"path": "event.payload.text", "op": "regex", "value": "a{0,64}b{0,64}c?"},
        {"path": "event.payload.text", "op": "regex", "value": r"(a)\1"},
        {"all": []},
        {"all": [{"path": "event.value", "op": "eq", "value": "x"}], "value": "ignored"},
        {"path": "event.payload.text", "op": "eq", "value": "x", "any": []},
    ],
)
def test_condition_rejects_unsafe_or_ambiguous_shapes(condition: dict) -> None:
    with pytest.raises(ValidationError):
        Condition.model_validate(condition)


def test_workflow_rejects_duplicate_steps_and_policy_expansion() -> None:
    duplicate = workflow_payload()
    duplicate["steps"] = [duplicate["steps"][0], duplicate["steps"][0]]
    with pytest.raises(ValidationError, match="step IDs must be unique"):
        WorkflowDefinition.model_validate(duplicate)

    undeclared_action = workflow_payload()
    undeclared_action["steps"][1]["action"] = "jira.create"
    with pytest.raises(ValidationError, match="policy.allowed_actions"):
        WorkflowDefinition.model_validate(undeclared_action)

    undeclared_tool = workflow_payload()
    undeclared_tool["steps"][0]["allowed_tools"].append("bash")
    with pytest.raises(ValidationError, match="outside policy.allowed_tools"):
        WorkflowDefinition.model_validate(undeclared_tool)


def test_silent_workflow_requires_explicit_approval_target() -> None:
    payload = workflow_payload(source_behavior="silent")
    payload["steps"] = [
        {
            "id": "approve",
            "type": "approval",
            "prompt": "Approve?",
            "approver_ids": ["U1"],
        }
    ]
    with pytest.raises(ValidationError, match="explicit target"):
        WorkflowDefinition.model_validate(payload)


def test_explicit_approval_target_requires_policy_destination() -> None:
    payload = workflow_payload(source_behavior="silent")
    payload["policy"] = {
        "channel_destinations": {"slack": ["C_ALLOWED"]},
    }
    payload["steps"] = [
        {
            "id": "approve",
            "type": "approval",
            "prompt": "Approve?",
            "approver_ids": ["U1"],
            "target": {"channel": "slack", "chat_id": "C_OTHER"},
        }
    ]

    with pytest.raises(ValidationError, match="approval target"):
        WorkflowDefinition.model_validate(payload)


def test_definition_revision_is_normalized_and_sensitive_to_behavior() -> None:
    first = WorkflowDefinition.model_validate(workflow_payload())
    same = WorkflowDefinition.model_validate(workflow_payload())
    changed = WorkflowDefinition.model_validate(workflow_payload(priority=11))

    assert definition_revision(first) == definition_revision(same)
    assert definition_revision(first) != definition_revision(changed)


def test_retry_backoff_rejects_non_finite_values() -> None:
    payload = workflow_payload(
        defaults={"retry": {"attempts": 2, "backoff_seconds": [float("nan")]}}
    )
    with pytest.raises(ValidationError, match="backoff values"):
        WorkflowDefinition.model_validate(payload)


def test_condition_accepts_finite_bounded_regex() -> None:
    condition = Condition.model_validate(
        {"path": "event.payload.text", "op": "regex", "value": "(?i)a{1,64}b?"}
    )
    assert condition.value == "(?i)a{1,64}b?"
