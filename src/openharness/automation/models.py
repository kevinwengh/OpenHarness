"""Versioned data contracts for event-driven automation workflows."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_EVENT_ANCESTRY = 16
MAX_CONDITION_DEPTH = 8
MAX_CONDITION_COUNT = 128
MAX_EVENT_JSON_BYTES = 256 * 1024
MAX_REGEX_PATTERN_LENGTH = 512
MAX_WORKFLOW_STEPS = 64

_EVENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
_PATH_RE = re.compile(r"^(event|run|steps)(?:\.[A-Za-z0-9_-]+)+$")
_OUTPUT_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$")


class AutomationModel(BaseModel):
    """Strict base model shared by persisted automation contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def validate_json_value(value: Any, *, path: str = "value", depth: int = 0) -> Any:
    if depth > 24:
        raise ValueError(f"{path} exceeds the maximum JSON nesting depth")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} contains a non-finite number")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        return [
            validate_json_value(item, path=f"{path}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            normalized[key] = validate_json_value(
                item,
                path=f"{path}.{key}",
                depth=depth + 1,
            )
        return normalized
    raise ValueError(f"{path} contains non-JSON value {type(value).__name__}")


def _validate_name(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(
            f"{label} must start with a lowercase letter and contain only lowercase "
            "letters, digits, dots, underscores, or hyphens"
        )
    return normalized


def validate_safe_regex(pattern: str) -> str:
    """Validate the deliberately small regex subset accepted by workflow rules."""

    if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
        raise ValueError(f"regex pattern exceeds {MAX_REGEX_PATTERN_LENGTH} characters")
    body = pattern
    inline_flags = re.match(r"^\(\?[aimsux]+\)", body)
    if inline_flags:
        body = body[inline_flags.end() :]
    if "(?" in body:
        raise ValueError("regex lookarounds and extended groups are not supported")
    if re.search(r"\\(?:[1-9]|g[<{])", body):
        raise ValueError("regex backreferences are not supported")
    if re.search(r"\([^()]*(?:\\.|\[[^]]*\]|[^()])*\)\s*(?:[*+?]|\{)", body):
        raise ValueError("quantified regex groups are not supported")
    if re.search(r"(?:[*+?]|\{\d+(?:,\d*)?\})\s*(?:[*+?]|\{)", body):
        raise ValueError("repeated regex quantifiers are not supported")
    _validate_regex_quantifier_cost(body)
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid regex pattern: {exc}") from exc
    return pattern


def _validate_regex_quantifier_cost(pattern: str) -> None:
    """Reject unbounded or combinatorially expensive quantifiers."""

    masked = re.sub(r"\\.", "", pattern)
    masked = re.sub(r"\[[^]]*\]", "", masked)
    if "*" in masked or "+" in masked:
        raise ValueError("unbounded regex quantifiers are not supported; use a finite {m,n} bound")
    expansion = 1
    for match in re.finditer(r"\?|\{(\d+)(?:,(\d+))?\}", masked):
        if match.group(0) == "?":
            choices = 2
        else:
            minimum = int(match.group(1))
            maximum_text = match.group(2)
            maximum = minimum if maximum_text is None else int(maximum_text)
            if maximum < minimum or maximum > 64:
                raise ValueError("regex repeat bounds must satisfy 0 <= min <= max <= 64")
            choices = maximum - minimum + 1
        expansion *= choices
        if expansion > 4096:
            raise ValueError("regex quantifier expansion exceeds the safe limit")


class EventSource(AutomationModel):
    adapter: str = Field(min_length=1, max_length=64)
    channel: str | None = Field(default=None, max_length=64)
    account: str | None = Field(default=None, max_length=128)
    instance: str | None = Field(default=None, max_length=128)


class EventActor(AutomationModel):
    id: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=256)


class EventSubject(AutomationModel):
    chat_id: str | None = Field(default=None, max_length=512)
    thread_id: str | None = Field(default=None, max_length=512)
    message_id: str | None = Field(default=None, max_length=512)


class AutomationEvent(AutomationModel):
    version: Literal[1] = 1
    id: str = Field(min_length=1, max_length=256)
    type: str = Field(min_length=1, max_length=256)
    occurred_at: datetime
    source: EventSource
    actor: EventActor
    subject: EventSubject = Field(default_factory=EventSubject)
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    automation_generated: bool = False
    ancestry: list[str] = Field(default_factory=list, max_length=MAX_EVENT_ANCESTRY)

    @field_validator("id", "type")
    @classmethod
    def _validate_event_name(cls, value: str) -> str:
        if not _EVENT_NAME_RE.fullmatch(value):
            raise ValueError("must contain only letters, digits, dots, underscores, colons, slashes, or hyphens")
        return value

    @field_validator("occurred_at")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("payload", "metadata")
    @classmethod
    def _validate_json_mapping(cls, value: dict[str, Any]) -> dict[str, Any]:
        normalized = validate_json_value(value)
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > MAX_EVENT_JSON_BYTES:
            raise ValueError(f"JSON mapping exceeds {MAX_EVENT_JSON_BYTES} bytes")
        return normalized

    @field_validator("ancestry")
    @classmethod
    def _validate_ancestry(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 256 for item in value):
            raise ValueError("ancestry entries must be non-empty and at most 256 characters")
        if len(value) != len(set(value)):
            raise ValueError("ancestry entries must be unique")
        return value


class TriggerSource(AutomationModel):
    adapter: str | None = Field(default=None, max_length=64)
    channel: str | None = Field(default=None, max_length=64)
    accounts: list[str] = Field(default_factory=list, max_length=100)
    chat_ids: list[str] = Field(default_factory=list, max_length=100)
    thread_ids: list[str] = Field(default_factory=list, max_length=100)
    actor_ids: list[str] = Field(default_factory=list, max_length=100)
    include_automation_generated: bool = False

    @field_validator("accounts", "chat_ids", "thread_ids", "actor_ids")
    @classmethod
    def _unique_filters(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item or len(item) > 512 for item in normalized):
            raise ValueError("source filter values must be non-empty and at most 512 characters")
        if len(normalized) != len(set(normalized)):
            raise ValueError("source filter values must be unique")
        return normalized


class WorkflowTrigger(AutomationModel):
    event: str = Field(min_length=1, max_length=256)
    source: TriggerSource = Field(default_factory=TriggerSource)

    @field_validator("event")
    @classmethod
    def _validate_event_type(cls, value: str) -> str:
        if not _EVENT_NAME_RE.fullmatch(value):
            raise ValueError("trigger event contains unsupported characters")
        return value


ConditionOperator = Literal[
    "eq",
    "ne",
    "in",
    "not_in",
    "contains",
    "starts_with",
    "ends_with",
    "glob",
    "regex",
    "exists",
    "gt",
    "gte",
    "lt",
    "lte",
]


class Condition(AutomationModel):
    path: str | None = None
    op: ConditionOperator | None = None
    value: Any = None
    all: list["Condition"] | None = None
    any: list["Condition"] | None = None
    not_condition: "Condition | None" = Field(default=None, alias="not")

    @model_validator(mode="after")
    def _validate_shape(self) -> "Condition":
        group_fields = [self.all is not None, self.any is not None, self.not_condition is not None]
        is_leaf = self.path is not None or self.op is not None
        if sum(group_fields) + int(is_leaf) != 1:
            raise ValueError("condition must define exactly one leaf, all, any, or not expression")
        if is_leaf:
            if self.path is None or self.op is None:
                raise ValueError("leaf condition requires both path and op")
            if not _PATH_RE.fullmatch(self.path):
                raise ValueError("condition path must start with event, run, or steps")
            if self.op == "regex":
                if not isinstance(self.value, str):
                    raise ValueError("regex condition value must be a string")
                validate_safe_regex(self.value)
            elif self.op == "exists":
                if self.value is not None and not isinstance(self.value, bool):
                    raise ValueError("exists condition value must be a boolean when provided")
            elif self.value is None:
                raise ValueError(f"{self.op} condition requires a value")
            validate_json_value(self.value)
        else:
            if self.value is not None:
                raise ValueError("condition groups cannot define a value")
            selected = self.all if self.all is not None else self.any
            if selected is not None and not selected:
                raise ValueError("condition groups cannot be empty")
        return self


class RetryPolicy(AutomationModel):
    attempts: int = Field(default=1, ge=1, le=10)
    backoff_seconds: list[float] = Field(default_factory=list, max_length=9)

    @field_validator("backoff_seconds")
    @classmethod
    def _validate_backoff(cls, value: list[float]) -> list[float]:
        if any(not math.isfinite(item) or item < 0 or item > 3600 for item in value):
            raise ValueError("backoff values must be between 0 and 3600 seconds")
        return value


class WorkflowDefaults(AutomationModel):
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)


class WorkflowConcurrency(AutomationModel):
    key: str = Field(min_length=1, max_length=1024)
    policy: Literal["serialize", "drop", "cancel_previous"] = "serialize"


class WorkflowPolicy(AutomationModel):
    allowed_actions: list[str] = Field(default_factory=list, max_length=128)
    allowed_tools: list[str] = Field(default_factory=list, max_length=128)
    channel_destinations: dict[str, list[str]] = Field(default_factory=dict)
    knowledge_namespaces: list[str] = Field(default_factory=list, max_length=128)

    @field_validator("allowed_actions", "allowed_tools", "knowledge_namespaces")
    @classmethod
    def _validate_policy_names(cls, value: list[str], info) -> list[str]:
        normalized = [_validate_name(item, label=info.field_name) for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"{info.field_name} entries must be unique")
        return normalized

    @field_validator("channel_destinations")
    @classmethod
    def _validate_destinations(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        normalized: dict[str, list[str]] = {}
        for channel, destinations in value.items():
            channel_name = _validate_name(channel, label="channel")
            items = [item.strip() for item in destinations]
            if not items or any(not item or len(item) > 512 for item in items):
                raise ValueError("channel destinations must be non-empty and at most 512 characters")
            if len(items) != len(set(items)):
                raise ValueError("channel destinations must be unique")
            normalized[channel_name] = items
        return normalized


class AgentOutputField(AutomationModel):
    type: Literal["string", "integer", "number", "boolean", "object", "array"]
    required: bool = True


class ApprovalTarget(AutomationModel):
    channel: str = Field(min_length=1, max_length=64)
    chat_id: str = Field(min_length=1, max_length=512)
    thread_id: str | None = Field(default=None, max_length=512)


class StepBase(AutomationModel):
    id: str
    when: Condition | None = None
    retry: RetryPolicy | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)

    @field_validator("id")
    @classmethod
    def _validate_step_id(cls, value: str) -> str:
        return _validate_name(value, label="step id")


class ActionStep(StepBase):
    type: Literal["action"]
    action: str
    arguments: dict[str, Any] = Field(default_factory=dict, alias="with")

    @field_validator("action")
    @classmethod
    def _validate_action(cls, value: str) -> str:
        return _validate_name(value, label="action")

    @field_validator("arguments")
    @classmethod
    def _validate_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_json_value(value)


class AgentStep(StepBase):
    type: Literal["agent"]
    skill: str
    model: str | None = Field(default=None, max_length=256)
    max_turns: int = Field(default=6, ge=1, le=50)
    allowed_tools: list[str] = Field(default_factory=list, max_length=128)
    output_schema: dict[str, AgentOutputField] = Field(min_length=1, max_length=128)

    @field_validator("skill")
    @classmethod
    def _validate_skill(cls, value: str) -> str:
        return _validate_name(value, label="skill")

    @field_validator("allowed_tools")
    @classmethod
    def _validate_tools(cls, value: list[str]) -> list[str]:
        normalized = [_validate_name(item, label="tool") for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed_tools entries must be unique")
        return normalized

    @field_validator("output_schema")
    @classmethod
    def _validate_output_schema(
        cls,
        value: dict[str, AgentOutputField],
    ) -> dict[str, AgentOutputField]:
        if any(not _OUTPUT_FIELD_RE.fullmatch(name) for name in value):
            raise ValueError("output field names must be identifiers")
        return value


class ApprovalStep(StepBase):
    type: Literal["approval"]
    prompt: str = Field(min_length=1, max_length=4000)
    approver_ids: list[str] = Field(min_length=1, max_length=100)
    expires_seconds: int = Field(default=900, ge=1, le=604800)
    target: ApprovalTarget | None = None

    @field_validator("approver_ids")
    @classmethod
    def _validate_approvers(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item or len(item) > 256 for item in normalized):
            raise ValueError("approver IDs must be non-empty and at most 256 characters")
        if len(normalized) != len(set(normalized)):
            raise ValueError("approver IDs must be unique")
        return normalized


WorkflowStep = Annotated[
    ActionStep | AgentStep | ApprovalStep,
    Field(discriminator="type"),
]


class WorkflowDefinition(AutomationModel):
    version: Literal[1]
    id: str
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    priority: int = Field(default=0, ge=-10000, le=10000)
    source_behavior: Literal["continue", "consume", "silent"] = "continue"
    trigger: WorkflowTrigger
    conditions: Condition | None = None
    concurrency: WorkflowConcurrency | None = None
    policy: WorkflowPolicy = Field(default_factory=WorkflowPolicy)
    defaults: WorkflowDefaults = Field(default_factory=WorkflowDefaults)
    steps: list[WorkflowStep] = Field(min_length=1, max_length=MAX_WORKFLOW_STEPS)

    @field_validator("id")
    @classmethod
    def _validate_workflow_id(cls, value: str) -> str:
        return _validate_name(value, label="workflow id")

    @model_validator(mode="after")
    def _validate_workflow(self) -> "WorkflowDefinition":
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("workflow step IDs must be unique")
        allowed_actions = set(self.policy.allowed_actions)
        allowed_tools = set(self.policy.allowed_tools)
        for step in self.steps:
            if isinstance(step, ActionStep) and step.action not in allowed_actions:
                raise ValueError(f"action {step.action!r} is not listed in policy.allowed_actions")
            if isinstance(step, AgentStep) and not set(step.allowed_tools).issubset(allowed_tools):
                raise ValueError(
                    f"agent step {step.id!r} allows tools outside policy.allowed_tools"
                )
            if (
                isinstance(step, ApprovalStep)
                and self.source_behavior == "silent"
                and step.target is None
            ):
                raise ValueError("silent workflows require an explicit target for approval steps")
        _validate_condition_limits(self.conditions)
        for step in self.steps:
            _validate_condition_limits(step.when)
        return self


def _validate_condition_limits(condition: Condition | None) -> None:
    if condition is None:
        return
    count = 0

    def visit(node: Condition, depth: int) -> None:
        nonlocal count
        count += 1
        if count > MAX_CONDITION_COUNT:
            raise ValueError(f"conditions exceed the maximum count of {MAX_CONDITION_COUNT}")
        if depth > MAX_CONDITION_DEPTH:
            raise ValueError(f"conditions exceed the maximum depth of {MAX_CONDITION_DEPTH}")
        children = node.all or node.any or ([] if node.not_condition is None else [node.not_condition])
        for child in children:
            visit(child, depth + 1)

    visit(condition, 1)


def definition_revision(definition: WorkflowDefinition) -> str:
    """Return a stable hash of the normalized validated workflow definition."""

    payload = definition.model_dump(mode="json", by_alias=True, exclude_none=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()
