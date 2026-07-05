from __future__ import annotations

import pytest

from openharness.automation.matcher import evaluate_condition, match_workflow
from openharness.automation.models import Condition


def test_workflow_matches_source_and_nested_condition(workflow, channel_event) -> None:
    trace = match_workflow(workflow, channel_event)

    assert trace.matched is True
    assert trace.outcomes[-1].operator == "regex"
    assert trace.outcomes[-1].matched is True


def test_workflow_rejects_wrong_source_and_generated_events(workflow, channel_event) -> None:
    wrong_source = channel_event.model_copy(
        update={"subject": channel_event.subject.model_copy(update={"chat_id": "C_OTHER"})}
    )
    assert match_workflow(workflow, wrong_source).matched is False

    generated = channel_event.model_copy(update={"automation_generated": True})
    trace = match_workflow(workflow, generated)
    assert trace.matched is False
    assert trace.outcomes[-1].reason == "generated events are excluded"


@pytest.mark.parametrize(
    ("condition", "context", "expected"),
    [
        ({"path": "event.value", "op": "eq", "value": 4}, {"event": {"value": 4}}, True),
        ({"path": "event.value", "op": "ne", "value": 3}, {"event": {"value": 4}}, True),
        ({"path": "event.value", "op": "in", "value": [3, 4]}, {"event": {"value": 4}}, True),
        ({"path": "event.value", "op": "not_in", "value": [3]}, {"event": {"value": 4}}, True),
        ({"path": "event.value", "op": "contains", "value": "b"}, {"event": {"value": ["a", "b"]}}, True),
        ({"path": "event.value", "op": "starts_with", "value": "pro"}, {"event": {"value": "production"}}, True),
        ({"path": "event.value", "op": "ends_with", "value": "tion"}, {"event": {"value": "production"}}, True),
        ({"path": "event.value", "op": "glob", "value": "prod*"}, {"event": {"value": "production"}}, True),
        ({"path": "event.value", "op": "regex", "value": "(?i)prod"}, {"event": {"value": "PRODUCTION"}}, True),
        ({"path": "event.value", "op": "exists"}, {"event": {"value": None}}, True),
        ({"path": "event.missing", "op": "exists", "value": False}, {"event": {}}, True),
        ({"path": "event.value", "op": "gt", "value": 3}, {"event": {"value": 4}}, True),
        ({"path": "event.value", "op": "gte", "value": 4}, {"event": {"value": 4}}, True),
        ({"path": "event.value", "op": "lt", "value": 5}, {"event": {"value": 4}}, True),
        ({"path": "event.value", "op": "lte", "value": 4}, {"event": {"value": 4}}, True),
    ],
)
def test_condition_operators(condition, context, expected) -> None:
    context.setdefault("run", {})
    context.setdefault("steps", {})
    matched, _ = evaluate_condition(Condition.model_validate(condition), context)
    assert matched is expected


def test_conditions_short_circuit_and_report_missing_or_wrong_types() -> None:
    condition = Condition.model_validate(
        {
            "all": [
                {"path": "event.missing", "op": "eq", "value": "x"},
                {"path": "event.value", "op": "gt", "value": 2},
            ]
        }
    )
    matched, outcomes = evaluate_condition(
        condition,
        {"event": {"value": True}, "run": {}, "steps": {}},
    )
    assert matched is False
    assert len(outcomes) == 1
    assert outcomes[0].reason == "path is missing"


def test_regex_input_is_bounded() -> None:
    condition = Condition.model_validate(
        {"path": "event.value", "op": "regex", "value": "a{1,64}$"}
    )
    matched, outcomes = evaluate_condition(
        condition,
        {"event": {"value": "a" * 9000}, "run": {}, "steps": {}},
    )
    assert matched is False
    assert "exceeds" in outcomes[0].reason


@pytest.mark.parametrize(
    ("condition", "actual"),
    [
        ({"path": "event.value", "op": "in", "value": "text"}, ["unhashable"]),
        ({"path": "event.value", "op": "contains", "value": ["unhashable"]}, {"key": True}),
    ],
)
def test_incompatible_membership_values_do_not_raise(condition, actual) -> None:
    matched, outcomes = evaluate_condition(
        Condition.model_validate(condition),
        {"event": {"value": actual}, "run": {}, "steps": {}},
    )
    assert matched is False
    assert "incompatible" in outcomes[0].reason
