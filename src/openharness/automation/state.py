"""Persisted workflow-run state and legal transition contracts."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from openharness.automation.models import (
    ApprovalStep,
    AutomationEvent,
    AutomationModel,
    WorkflowDefinition,
    definition_revision,
    validate_json_value,
)

RunStatus = Literal[
    "pending",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
]
StepStatus = Literal[
    "pending",
    "running",
    "skipped",
    "waiting_approval",
    "completed",
    "failed",
]
AttemptStatus = Literal["running", "completed", "failed", "outcome_unknown"]
ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]

MAX_STEP_IO_BYTES = 256 * 1024
_RUN_ID_RE = re.compile(r"^run-[A-Za-z0-9._-]{8,128}$")

RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "cancelled"}),
    "running": frozenset({"pending", "waiting_approval", "completed", "failed", "cancelled"}),
    "waiting_approval": frozenset({"pending", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset({"pending"}),
    "cancelled": frozenset(),
}

STEP_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "skipped", "waiting_approval"}),
    "running": frozenset({"pending", "completed", "failed"}),
    "waiting_approval": frozenset({"pending", "completed", "failed"}),
    "skipped": frozenset(),
    "completed": frozenset(),
    "failed": frozenset({"pending"}),
}


class TransitionError(RuntimeError):
    """Raised when a requested persisted state transition is illegal."""


class RunError(AutomationModel):
    category: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    retryable: bool = False
    outcome_unknown: bool = False


class StepAttempt(AutomationModel):
    number: int = Field(ge=1, le=1000)
    status: AttemptStatus
    retry_safe: bool
    logical_idempotency_key: str = Field(min_length=1, max_length=512)
    attempt_idempotency_key: str = Field(min_length=1, max_length=512)
    started_at: datetime
    completed_at: datetime | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: RunError | None = None

    @field_validator("input")
    @classmethod
    def _validate_input(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json_mapping(value, label="step input")

    @field_validator("output")
    @classmethod
    def _validate_output(cls, value: Any) -> Any:
        if value is None:
            return None
        return _bounded_json_value(value, label="step output")

    @field_validator("started_at", "completed_at")
    @classmethod
    def _validate_timestamps(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def _validate_status(self) -> "StepAttempt":
        if self.status == "running":
            if self.completed_at is not None or self.error is not None:
                raise ValueError("running attempts cannot have completion state")
        elif self.completed_at is None:
            raise ValueError("terminal attempts require completed_at")
        if self.status == "completed" and self.error is not None:
            raise ValueError("completed attempts cannot have an error")
        if self.status in {"failed", "outcome_unknown"} and self.error is None:
            raise ValueError("failed attempts require an error")
        if self.status == "outcome_unknown" and not self.error.outcome_unknown:
            raise ValueError("outcome_unknown attempts require an outcome_unknown error")
        return self


class StepRun(AutomationModel):
    id: str
    type: Literal["action", "agent", "approval"]
    status: StepStatus = "pending"
    attempts: list[StepAttempt] = Field(default_factory=list, max_length=1000)
    output: Any = None
    error: RunError | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("output")
    @classmethod
    def _validate_output(cls, value: Any) -> Any:
        if value is None:
            return None
        return _bounded_json_value(value, label="step output")

    @field_validator("started_at", "completed_at")
    @classmethod
    def _validate_timestamps(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def _validate_status(self) -> "StepRun":
        if self.status == "running":
            if not self.attempts or self.attempts[-1].status != "running":
                raise ValueError("running steps require an active attempt")
            if self.completed_at is not None:
                raise ValueError("running steps cannot have completed_at")
        if self.status in {"completed", "skipped", "failed"} and self.completed_at is None:
            raise ValueError("terminal steps require completed_at")
        if self.status == "failed" and self.error is None:
            raise ValueError("failed steps require an error")
        if self.status == "completed" and self.error is not None:
            raise ValueError("completed steps cannot have an error")
        if self.status != "running" and any(
            attempt.status == "running" for attempt in self.attempts
        ):
            raise ValueError("only a running step may contain an active attempt")
        return self


class ApprovalRecord(AutomationModel):
    step_id: str
    status: ApprovalStatus = "pending"
    prompt: str = Field(min_length=1, max_length=4000)
    approver_ids: list[str] = Field(min_length=1, max_length=100)
    requested_at: datetime
    expires_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str | None = Field(default=None, max_length=256)
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("requested_at", "expires_at", "resolved_at")
    @classmethod
    def _validate_timestamps(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def _validate_status(self) -> "ApprovalRecord":
        if self.expires_at <= self.requested_at:
            raise ValueError("approval expiry must be after its request time")
        if self.status == "pending":
            if self.resolved_at is not None or self.resolved_by is not None:
                raise ValueError("pending approvals cannot have resolution state")
        elif self.resolved_at is None:
            raise ValueError("resolved approvals require resolved_at")
        return self


class WorkflowRun(AutomationModel):
    version: Literal[1] = 1
    id: str
    workflow_id: str
    definition_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    definition: WorkflowDefinition
    event: AutomationEvent
    source_behavior: Literal["continue", "consume", "silent"]
    status: RunStatus = "pending"
    steps: list[StepRun]
    current_step: int = Field(default=0, ge=0)
    context: dict[str, Any] = Field(default_factory=dict)
    concurrency_key: str | None = Field(default=None, max_length=1024)
    approvals: list[ApprovalRecord] = Field(default_factory=list, max_length=100)
    created_at: datetime
    started_at: datetime | None = None
    updated_at: datetime
    completed_at: datetime | None = None
    error: RunError | None = None

    @field_validator("id")
    @classmethod
    def _validate_run_id(cls, value: str) -> str:
        if not _RUN_ID_RE.fullmatch(value):
            raise ValueError("invalid workflow run ID")
        return value

    @field_validator("context")
    @classmethod
    def _validate_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json_mapping(value, label="run context")

    @field_validator("created_at", "started_at", "updated_at", "completed_at")
    @classmethod
    def _validate_timestamps(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def _validate_consistency(self) -> "WorkflowRun":
        if self.workflow_id != self.definition.id:
            raise ValueError("workflow_id does not match the stored definition")
        if self.definition_revision != definition_revision(self.definition):
            raise ValueError("definition_revision does not match the stored definition")
        expected = [(step.id, step.type) for step in self.definition.steps]
        actual = [(step.id, step.type) for step in self.steps]
        if actual != expected:
            raise ValueError("run steps do not match the stored definition")
        if self.current_step > len(self.steps):
            raise ValueError("current_step exceeds the workflow step count")
        first_unfinished = next(
            (
                index
                for index, step in enumerate(self.steps)
                if step.status not in {"completed", "skipped"}
            ),
            len(self.steps),
        )
        if self.current_step != first_unfinished:
            raise ValueError("current_step must identify the first unfinished workflow step")
        if any(
            step.status != "pending"
            for step in self.steps[self.current_step + 1 :]
        ):
            raise ValueError("steps after the current step must remain pending")
        active_attempts = sum(
            attempt.status == "running"
            for step in self.steps
            for attempt in step.attempts
        )
        if active_attempts > 1:
            raise ValueError("a sequential workflow run cannot have multiple active attempts")
        if self.status == "completed":
            if self.current_step != len(self.steps):
                raise ValueError("completed runs must advance past every step")
            if any(step.status not in {"completed", "skipped"} for step in self.steps):
                raise ValueError("completed runs require every step to be completed or skipped")
        if self.status == "waiting_approval":
            if self.current_step >= len(self.steps):
                raise ValueError("waiting runs require a current approval step")
            if self.steps[self.current_step].status != "waiting_approval":
                raise ValueError("waiting runs require a waiting approval step")
            if not self.approvals or self.approvals[-1].status != "pending":
                raise ValueError("waiting runs require a pending approval record")
        if self.status in {"completed", "failed", "cancelled"} and self.completed_at is None:
            raise ValueError("terminal runs require completed_at")
        if self.status not in {"completed", "failed", "cancelled"} and self.completed_at is not None:
            raise ValueError("non-terminal runs cannot have completed_at")
        if self.status in {"failed", "cancelled"} and self.error is None:
            raise ValueError("failed and cancelled runs require an error")
        return self


def new_workflow_run(
    definition: WorkflowDefinition,
    event: AutomationEvent,
    *,
    run_id: str,
    now: datetime,
    concurrency_key: str | None = None,
) -> WorkflowRun:
    timestamp = _utc(now)
    return WorkflowRun(
        id=run_id,
        workflow_id=definition.id,
        definition_revision=definition_revision(definition),
        definition=definition,
        event=event,
        source_behavior=definition.source_behavior,
        steps=[StepRun(id=step.id, type=step.type) for step in definition.steps],
        concurrency_key=concurrency_key,
        created_at=timestamp,
        updated_at=timestamp,
    )


def ensure_run_transition(current: str, target: str) -> None:
    if target not in RUN_TRANSITIONS.get(current, frozenset()):
        raise TransitionError(f"illegal run transition: {current} -> {target}")


def ensure_step_transition(current: str, target: str) -> None:
    if target not in STEP_TRANSITIONS.get(current, frozenset()):
        raise TransitionError(f"illegal step transition: {current} -> {target}")


def approval_step_for(run: WorkflowRun, step_id: str) -> ApprovalStep:
    for step in run.definition.steps:
        if step.id == step_id and isinstance(step, ApprovalStep):
            return step
    raise TransitionError(f"step {step_id!r} is not an approval step")


def _bounded_json_mapping(value: dict[str, Any], *, label: str) -> dict[str, Any]:
    normalized = validate_json_value(value, path=label)
    _ensure_json_size(normalized, label=label)
    return normalized


def _bounded_json_value(value: Any, *, label: str) -> Any:
    normalized = validate_json_value(value, path=label)
    _ensure_json_size(normalized, label=label)
    return normalized


def _ensure_json_size(value: Any, *, label: str) -> None:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > MAX_STEP_IO_BYTES:
        raise ValueError(f"{label} exceeds {MAX_STEP_IO_BYTES} bytes")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("workflow timestamps must include a timezone")
    return value.astimezone(timezone.utc)
