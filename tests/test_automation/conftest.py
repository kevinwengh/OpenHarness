from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from openharness.automation.models import AutomationEvent, WorkflowDefinition


@pytest.fixture
def channel_event() -> AutomationEvent:
    return AutomationEvent.model_validate(
        {
            "id": "Ev-123",
            "type": "channel.message",
            "occurred_at": datetime(2026, 7, 5, tzinfo=timezone.utc),
            "source": {"adapter": "channel", "channel": "slack", "account": "primary"},
            "actor": {"id": "U_ALLOWED", "display_name": "Operator"},
            "subject": {"chat_id": "C_ALERTS", "thread_id": "T_1", "message_id": "M_1"},
            "payload": {"text": "Production is DOWN", "severity": 9, "labels": ["prod"]},
        }
    )


def workflow_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": 1,
        "id": "incident-routing",
        "description": "Route production incidents",
        "priority": 10,
        "source_behavior": "consume",
        "trigger": {
            "event": "channel.message",
            "source": {
                "channel": "slack",
                "chat_ids": ["C_ALERTS"],
                "actor_ids": ["U_ALLOWED"],
            },
        },
        "conditions": {
            "any": [
                {"path": "event.payload.text", "op": "regex", "value": "(?i)(down|critical)"},
                {"path": "event.payload.labels", "op": "contains", "value": "incident"},
            ]
        },
        "policy": {
            "allowed_actions": ["channel.send"],
            "allowed_tools": ["slack_history"],
            "channel_destinations": {"slack": ["C_OPS"]},
        },
        "steps": [
            {
                "id": "assess",
                "type": "agent",
                "skill": "incident-triage",
                "allowed_tools": ["slack_history"],
                "output_schema": {
                    "summary": {"type": "string"},
                    "customer_impact": {"type": "boolean"},
                },
            },
            {
                "id": "notify",
                "type": "action",
                "action": "channel.send",
                "with": {"channel": "slack", "chat_id": "C_OPS", "content": "${steps.assess.output.summary}"},
            },
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def workflow() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(workflow_payload())
