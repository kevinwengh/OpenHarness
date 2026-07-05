"""Deterministic source and condition matching for automation workflows."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from numbers import Real
from typing import Any

from openharness.automation.models import AutomationEvent, Condition, WorkflowDefinition

MAX_REGEX_INPUT_LENGTH = 8192
_MISSING = object()


@dataclass(frozen=True)
class ConditionOutcome:
    path: str
    operator: str
    matched: bool
    reason: str


@dataclass(frozen=True)
class MatchTrace:
    matched: bool
    outcomes: tuple[ConditionOutcome, ...]


def match_workflow(
    definition: WorkflowDefinition,
    event: AutomationEvent,
    *,
    run: dict[str, Any] | None = None,
    steps: dict[str, Any] | None = None,
) -> MatchTrace:
    """Return a traceable match decision for one workflow and event."""

    outcomes: list[ConditionOutcome] = []
    trigger_matches = definition.enabled and definition.trigger.event == event.type
    outcomes.append(
        ConditionOutcome(
            path="event.type",
            operator="eq",
            matched=trigger_matches,
            reason="trigger event matched" if trigger_matches else "workflow disabled or event type differs",
        )
    )
    if not trigger_matches:
        return MatchTrace(False, tuple(outcomes))

    for path, expected, actual in _source_checks(definition, event):
        matched = actual in expected if isinstance(expected, tuple) else actual == expected
        outcomes.append(
            ConditionOutcome(
                path=path,
                operator="in" if isinstance(expected, tuple) else "eq",
                matched=matched,
                reason="source filter matched" if matched else "source filter did not match",
            )
        )
        if not matched:
            return MatchTrace(False, tuple(outcomes))

    if event.automation_generated and not definition.trigger.source.include_automation_generated:
        outcomes.append(
            ConditionOutcome(
                path="event.automation_generated",
                operator="eq",
                matched=False,
                reason="generated events are excluded",
            )
        )
        return MatchTrace(False, tuple(outcomes))

    if definition.conditions is None:
        return MatchTrace(True, tuple(outcomes))
    context = {
        "event": event.model_dump(mode="json"),
        "run": run or {},
        "steps": steps or {},
    }
    matched, condition_outcomes = evaluate_condition(definition.conditions, context)
    outcomes.extend(condition_outcomes)
    return MatchTrace(matched, tuple(outcomes))


def _source_checks(
    definition: WorkflowDefinition,
    event: AutomationEvent,
) -> list[tuple[str, str | tuple[str, ...], str | None]]:
    source = definition.trigger.source
    checks: list[tuple[str, str | tuple[str, ...], str | None]] = []
    if source.adapter is not None:
        checks.append(("event.source.adapter", source.adapter, event.source.adapter))
    if source.channel is not None:
        checks.append(("event.source.channel", source.channel, event.source.channel))
    if source.accounts:
        checks.append(("event.source.account", tuple(source.accounts), event.source.account))
    if source.chat_ids:
        checks.append(("event.subject.chat_id", tuple(source.chat_ids), event.subject.chat_id))
    if source.thread_ids:
        checks.append(("event.subject.thread_id", tuple(source.thread_ids), event.subject.thread_id))
    if source.actor_ids:
        checks.append(("event.actor.id", tuple(source.actor_ids), event.actor.id))
    return checks


def evaluate_condition(
    condition: Condition,
    context: dict[str, Any],
) -> tuple[bool, tuple[ConditionOutcome, ...]]:
    """Evaluate a validated condition and return leaf-level outcomes."""

    outcomes: list[ConditionOutcome] = []

    def evaluate(node: Condition) -> bool:
        if node.all is not None:
            return all(evaluate(child) for child in node.all)
        if node.any is not None:
            return any(evaluate(child) for child in node.any)
        if node.not_condition is not None:
            return not evaluate(node.not_condition)
        assert node.path is not None and node.op is not None
        actual = resolve_path(context, node.path)
        matched, reason = _apply_operator(actual, node.op, node.value)
        outcomes.append(ConditionOutcome(node.path, node.op, matched, reason))
        return matched

    return evaluate(condition), tuple(outcomes)


def resolve_path(context: dict[str, Any], path: str) -> Any:
    current: Any = context
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _apply_operator(actual: Any, operator: str, expected: Any) -> tuple[bool, str]:
    exists = actual is not _MISSING
    if operator == "exists":
        wanted = True if expected is None else expected
        return exists is wanted, "path existence matched" if exists is wanted else "path existence differed"
    if not exists:
        return False, "path is missing"
    if operator == "eq":
        return actual == expected, "values compared"
    if operator == "ne":
        return actual != expected, "values compared"
    if operator in {"in", "not_in"}:
        if not isinstance(expected, (list, tuple, set, dict, str)):
            return False, "expected value is not a container"
        try:
            contained = actual in expected
        except TypeError:
            return False, "membership values are incompatible"
        return (contained if operator == "in" else not contained), "membership compared"
    if operator == "contains":
        if not isinstance(actual, (list, tuple, set, dict, str)):
            return False, "actual value is not a container"
        try:
            return expected in actual, "containment compared"
        except TypeError:
            return False, "containment values are incompatible"
    if operator in {"starts_with", "ends_with", "glob", "regex"}:
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False, "string operator requires string values"
        if operator == "starts_with":
            return actual.startswith(expected), "prefix compared"
        if operator == "ends_with":
            return actual.endswith(expected), "suffix compared"
        if operator == "glob":
            return fnmatch.fnmatchcase(actual, expected), "glob compared"
        if len(actual) > MAX_REGEX_INPUT_LENGTH:
            return False, f"regex input exceeds {MAX_REGEX_INPUT_LENGTH} characters"
        return re.search(expected, actual) is not None, "regex searched"
    if operator in {"gt", "gte", "lt", "lte"}:
        if (
            isinstance(actual, bool)
            or isinstance(expected, bool)
            or not isinstance(actual, Real)
            or not isinstance(expected, Real)
        ):
            return False, "numeric comparison requires numbers"
        if operator == "gt":
            return actual > expected, "numbers compared"
        if operator == "gte":
            return actual >= expected, "numbers compared"
        if operator == "lt":
            return actual < expected, "numbers compared"
        return actual <= expected, "numbers compared"
    return False, f"unsupported operator {operator}"
