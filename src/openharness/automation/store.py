"""Crash-aware local persistence for workflow runs and event reservations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from pydantic import ValidationError

from openharness.automation.models import ApprovalStep, AutomationEvent, WorkflowDefinition
from openharness.automation.state import (
    ApprovalRecord,
    RunError,
    StepAttempt,
    StepRun,
    TransitionError,
    WorkflowRun,
    approval_step_for,
    ensure_run_transition,
    ensure_step_transition,
    new_workflow_run,
)
from openharness.utils.file_lock import exclusive_file_lock
from openharness.utils.fs import atomic_write_text

MAX_RUN_BYTES = 4 * 1024 * 1024
MAX_INDEX_BYTES = 4 * 1024 * 1024


class AutomationStoreError(RuntimeError):
    """Raised when durable automation state cannot be read or transitioned."""


@dataclass(frozen=True)
class ReservationResult:
    run: WorkflowRun
    created: bool


@dataclass(frozen=True)
class RecoveryResult:
    recovered_run_ids: tuple[str, ...]
    outcome_unknown_run_ids: tuple[str, ...]
    diagnostics: tuple[str, ...]


class AutomationStore:
    """Own atomic run checkpoints and workflow/event idempotency reservations."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.runs_dir = self.root / "runs"
        self.archive_dir = self.root / "archive"
        self.index_path = self.root / "index.json"
        self.lock_path = self.root / ".lock"
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or self._new_run_id
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def reserve(
        self,
        definition: WorkflowDefinition,
        event: AutomationEvent,
        *,
        concurrency_key: str | None = None,
    ) -> ReservationResult:
        """Atomically reserve one workflow/event pair and create its pending run."""

        with exclusive_file_lock(self.lock_path):
            index, _ = self._load_or_rebuild_index_locked()
            reservation_key = _reservation_key(definition.id, event.id)
            entry = index["reservations"].get(reservation_key)
            if isinstance(entry, dict):
                run_id = str(entry.get("run_id") or "")
                existing = self._load_run_if_present_locked(run_id)
                if existing is not None:
                    _verify_reservation(existing, definition.id, event.id)
                    return ReservationResult(existing, False)

            orphan = self._find_run_locked(definition.id, event.id)
            if orphan is not None:
                self._index_run(index, orphan)
                self._write_index_locked(index)
                return ReservationResult(orphan, False)

            now = _utc(self._clock())
            run_id = self._next_available_run_id_locked()
            run = new_workflow_run(
                definition,
                event,
                run_id=run_id,
                now=now,
                concurrency_key=concurrency_key,
            )
            self._write_run_locked(run)
            self._index_run(index, run)
            self._write_index_locked(index)
            return ReservationResult(run, True)

    def load_run(self, run_id: str) -> WorkflowRun:
        path = self._run_path(run_id)
        try:
            raw = json.loads(self._read_bounded(path, MAX_RUN_BYTES, "workflow run"))
            return WorkflowRun.model_validate(raw)
        except FileNotFoundError as exc:
            raise AutomationStoreError(f"workflow run not found: {run_id}") from exc
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise AutomationStoreError(f"cannot load workflow run {run_id}: {exc}") from exc

    def list_runs(
        self,
        *,
        workflow_id: str | None = None,
        status: str | None = None,
    ) -> tuple[WorkflowRun, ...]:
        runs: list[WorkflowRun] = []
        for path in sorted(self.runs_dir.glob("run-*.json")):
            try:
                run = WorkflowRun.model_validate_json(
                    self._read_bounded(path, MAX_RUN_BYTES, "workflow run")
                )
            except (OSError, ValidationError, AutomationStoreError):
                continue
            if workflow_id is not None and run.workflow_id != workflow_id:
                continue
            if status is not None and run.status != status:
                continue
            runs.append(run)
        return tuple(sorted(runs, key=lambda run: (run.created_at, run.id), reverse=True))

    def transition_run(
        self,
        run_id: str,
        target: str,
        *,
        error: RunError | None = None,
    ) -> WorkflowRun:
        with exclusive_file_lock(self.lock_path):
            run = self._load_run_locked(run_id)
            if target not in {"running", "completed"}:
                raise TransitionError(
                    f"run transition to {target!r} requires its specialized store operation"
                )
            ensure_run_transition(run.status, target)
            if target == "completed" and (
                run.current_step != len(run.steps)
                or any(step.status not in {"completed", "skipped"} for step in run.steps)
            ):
                raise TransitionError("cannot complete a run before every step is terminal")
            now = _utc(self._clock())
            updates: dict[str, Any] = {"status": target, "updated_at": now, "error": error}
            if target == "running" and run.started_at is None:
                updates["started_at"] = now
            if target in {"completed", "failed", "cancelled"}:
                updates["completed_at"] = now
            if target == "pending":
                updates["completed_at"] = None
            updated = run.model_copy(update=updates)
            return self._checkpoint_locked(updated)

    def start_step(
        self,
        run_id: str,
        step_id: str,
        *,
        input: dict[str, Any] | None = None,
        retry_safe: bool,
    ) -> WorkflowRun:
        with exclusive_file_lock(self.lock_path):
            run = self._load_run_locked(run_id)
            if run.status not in {"pending", "running"}:
                raise TransitionError(f"cannot start a step while run is {run.status}")
            index, step = _step_by_id(run, step_id)
            if index != run.current_step:
                raise TransitionError(f"step {step_id!r} is not the current step")
            ensure_step_transition(step.status, "running")
            definition_step = run.definition.steps[index]
            if isinstance(definition_step, ApprovalStep):
                raise TransitionError("approval steps must use wait_for_approval")
            retry = definition_step.retry or run.definition.defaults.retry
            attempt_number = len(step.attempts) + 1
            if attempt_number > retry.attempts:
                raise TransitionError(f"step {step_id!r} exhausted its {retry.attempts} attempts")
            now = _utc(self._clock())
            attempt = StepAttempt(
                number=attempt_number,
                status="running",
                retry_safe=retry_safe,
                logical_idempotency_key=f"{run.id}:{step.id}",
                attempt_idempotency_key=f"{run.id}:{step.id}:{attempt_number}",
                started_at=now,
                input=input or {},
            )
            updated_step = step.model_copy(
                update={
                    "status": "running",
                    "attempts": [*step.attempts, attempt],
                    "started_at": step.started_at or now,
                    "completed_at": None,
                    "error": None,
                }
            )
            run_updates: dict[str, Any] = {
                "status": "running",
                "started_at": run.started_at or now,
                "updated_at": now,
                "error": None,
                "completed_at": None,
            }
            updated = _replace_step(run, index, updated_step).model_copy(update=run_updates)
            return self._checkpoint_locked(updated)

    def complete_step(self, run_id: str, step_id: str, *, output: Any) -> WorkflowRun:
        with exclusive_file_lock(self.lock_path):
            run = self._load_run_locked(run_id)
            if run.status != "running":
                raise TransitionError(f"cannot complete a step while run is {run.status}")
            index, step = _step_by_id(run, step_id)
            if index != run.current_step:
                raise TransitionError(f"step {step_id!r} is not the current step")
            ensure_step_transition(step.status, "completed")
            attempt = _active_attempt(step)
            now = _utc(self._clock())
            completed_attempt = attempt.model_copy(
                update={"status": "completed", "completed_at": now, "output": output}
            )
            updated_step = step.model_copy(
                update={
                    "status": "completed",
                    "attempts": [*step.attempts[:-1], completed_attempt],
                    "output": output,
                    "completed_at": now,
                    "error": None,
                }
            )
            context = dict(run.context)
            step_context = dict(context.get("steps") or {})
            step_context[step.id] = {"output": output}
            context["steps"] = step_context
            updated = _replace_step(run, index, updated_step).model_copy(
                update={
                    "current_step": index + 1,
                    "context": context,
                    "updated_at": now,
                }
            )
            return self._checkpoint_locked(updated)

    def fail_step(
        self,
        run_id: str,
        step_id: str,
        *,
        error: RunError,
        outcome_unknown: bool = False,
    ) -> WorkflowRun:
        with exclusive_file_lock(self.lock_path):
            run = self._load_run_locked(run_id)
            if run.status != "running":
                raise TransitionError(f"cannot fail a step while run is {run.status}")
            index, step = _step_by_id(run, step_id)
            if index != run.current_step:
                raise TransitionError(f"step {step_id!r} is not the current step")
            ensure_step_transition(step.status, "failed")
            attempt = _active_attempt(step)
            now = _utc(self._clock())
            normalized_error = error.model_copy(update={"outcome_unknown": outcome_unknown})
            completed_attempt = attempt.model_copy(
                update={
                    "status": "outcome_unknown" if outcome_unknown else "failed",
                    "completed_at": now,
                    "error": normalized_error,
                }
            )
            updated_step = step.model_copy(
                update={
                    "status": "failed",
                    "attempts": [*step.attempts[:-1], completed_attempt],
                    "completed_at": now,
                    "error": normalized_error,
                }
            )
            updated = _replace_step(run, index, updated_step).model_copy(
                update={
                    "status": "failed",
                    "updated_at": now,
                    "completed_at": now,
                    "error": normalized_error,
                }
            )
            return self._checkpoint_locked(updated)

    def skip_step(self, run_id: str, step_id: str) -> WorkflowRun:
        with exclusive_file_lock(self.lock_path):
            run = self._load_run_locked(run_id)
            if run.status not in {"pending", "running"}:
                raise TransitionError(f"cannot skip a step while run is {run.status}")
            index, step = _step_by_id(run, step_id)
            if index != run.current_step:
                raise TransitionError(f"step {step_id!r} is not the current step")
            ensure_step_transition(step.status, "skipped")
            now = _utc(self._clock())
            updated_step = step.model_copy(
                update={"status": "skipped", "completed_at": now}
            )
            updated = _replace_step(run, index, updated_step).model_copy(
                update={"current_step": index + 1, "updated_at": now}
            )
            return self._checkpoint_locked(updated)

    def wait_for_approval(self, run_id: str, step_id: str) -> WorkflowRun:
        with exclusive_file_lock(self.lock_path):
            run = self._load_run_locked(run_id)
            if run.status not in {"pending", "running"}:
                raise TransitionError(f"cannot wait for approval while run is {run.status}")
            index, step = _step_by_id(run, step_id)
            if index != run.current_step:
                raise TransitionError(f"step {step_id!r} is not the current step")
            ensure_step_transition(step.status, "waiting_approval")
            definition_step = approval_step_for(run, step_id)
            now = _utc(self._clock())
            approval = ApprovalRecord(
                step_id=step_id,
                prompt=definition_step.prompt,
                approver_ids=definition_step.approver_ids,
                requested_at=now,
                expires_at=now + timedelta(seconds=definition_step.expires_seconds),
            )
            updated_step = step.model_copy(
                update={"status": "waiting_approval", "started_at": now}
            )
            updated = _replace_step(run, index, updated_step).model_copy(
                update={
                    "status": "waiting_approval",
                    "approvals": [*run.approvals, approval],
                    "updated_at": now,
                }
            )
            return self._checkpoint_locked(updated)

    def resolve_approval(
        self,
        run_id: str,
        *,
        actor_id: str,
        approved: bool,
        reason: str | None = None,
    ) -> WorkflowRun:
        with exclusive_file_lock(self.lock_path):
            run = self._load_run_locked(run_id)
            if run.status != "waiting_approval" or not run.approvals:
                raise TransitionError("run is not waiting for approval")
            approval = run.approvals[-1]
            if approval.status != "pending":
                raise TransitionError("approval is already resolved")
            if actor_id not in approval.approver_ids:
                raise TransitionError(f"actor {actor_id!r} is not allowed to approve this run")
            now = _utc(self._clock())
            expired = now >= approval.expires_at
            status = "expired" if expired else ("approved" if approved else "rejected")
            resolved = approval.model_copy(
                update={
                    "status": status,
                    "resolved_at": now,
                    "resolved_by": actor_id,
                    "reason": reason,
                }
            )
            index, step = _step_by_id(run, approval.step_id)
            if expired or not approved:
                error = RunError(
                    category="approval_expired" if expired else "approval_rejected",
                    message="approval expired" if expired else (reason or "approval rejected"),
                )
                updated_step = step.model_copy(
                    update={"status": "failed", "completed_at": now, "error": error}
                )
                updated = _replace_step(run, index, updated_step).model_copy(
                    update={
                        "status": "failed",
                        "approvals": [*run.approvals[:-1], resolved],
                        "updated_at": now,
                        "completed_at": now,
                        "error": error,
                    }
                )
            else:
                updated_step = step.model_copy(
                    update={"status": "completed", "completed_at": now}
                )
                updated = _replace_step(run, index, updated_step).model_copy(
                    update={
                        "status": "pending",
                        "current_step": index + 1,
                        "approvals": [*run.approvals[:-1], resolved],
                        "updated_at": now,
                    }
                )
            return self._checkpoint_locked(updated)

    def retry_run(self, run_id: str, *, allow_unknown_outcome: bool = False) -> WorkflowRun:
        with exclusive_file_lock(self.lock_path):
            run = self._load_run_locked(run_id)
            if run.status != "failed":
                raise TransitionError("only failed runs can be retried")
            if run.error and run.error.outcome_unknown and not allow_unknown_outcome:
                raise TransitionError("outcome is unknown; explicit override is required")
            index = run.current_step
            if index >= len(run.steps):
                raise TransitionError("failed run has no current step to retry")
            step = run.steps[index]
            ensure_step_transition(step.status, "pending")
            now = _utc(self._clock())
            updated_step = step.model_copy(
                update={"status": "pending", "completed_at": None, "error": None}
            )
            updated = _replace_step(run, index, updated_step).model_copy(
                update={
                    "status": "pending",
                    "updated_at": now,
                    "completed_at": None,
                    "error": None,
                }
            )
            return self._checkpoint_locked(updated)

    def cancel_run(self, run_id: str, *, reason: str = "cancelled by operator") -> WorkflowRun:
        with exclusive_file_lock(self.lock_path):
            run = self._load_run_locked(run_id)
            ensure_run_transition(run.status, "cancelled")
            now = _utc(self._clock())
            error = RunError(category="cancelled", message=reason)
            updated = run
            approvals = list(run.approvals)
            if run.current_step < len(run.steps):
                step = run.steps[run.current_step]
                if step.status == "running":
                    attempt = _active_attempt(step).model_copy(
                        update={"status": "failed", "completed_at": now, "error": error}
                    )
                    step = step.model_copy(
                        update={
                            "status": "failed",
                            "attempts": [*step.attempts[:-1], attempt],
                            "completed_at": now,
                            "error": error,
                        }
                    )
                    updated = _replace_step(run, run.current_step, step)
                elif step.status == "waiting_approval":
                    step = step.model_copy(
                        update={"status": "failed", "completed_at": now, "error": error}
                    )
                    updated = _replace_step(run, run.current_step, step)
                    if approvals and approvals[-1].status == "pending":
                        approvals[-1] = approvals[-1].model_copy(
                            update={
                                "status": "rejected",
                                "resolved_at": now,
                                "reason": reason,
                            }
                        )
            updated = updated.model_copy(
                update={
                    "status": "cancelled",
                    "approvals": approvals,
                    "updated_at": now,
                    "completed_at": now,
                    "error": error,
                }
            )
            return self._checkpoint_locked(updated)

    def recover(self) -> RecoveryResult:
        recovered: list[str] = []
        unknown: list[str] = []
        diagnostics: list[str] = []
        with exclusive_file_lock(self.lock_path):
            for path in sorted(self.runs_dir.glob("run-*.json")):
                try:
                    run = WorkflowRun.model_validate_json(
                        self._read_bounded(path, MAX_RUN_BYTES, "workflow run")
                    )
                except (OSError, ValidationError, AutomationStoreError) as exc:
                    diagnostics.append(f"{path.name}: {exc}")
                    continue
                now = _utc(self._clock())
                if run.status == "waiting_approval":
                    approval = run.approvals[-1]
                    if approval.expires_at <= now:
                        error = RunError(category="approval_expired", message="approval expired")
                        resolved = approval.model_copy(
                            update={"status": "expired", "resolved_at": now}
                        )
                        step = run.steps[run.current_step].model_copy(
                            update={"status": "failed", "completed_at": now, "error": error}
                        )
                        updated = _replace_step(run, run.current_step, step).model_copy(
                            update={
                                "status": "failed",
                                "approvals": [*run.approvals[:-1], resolved],
                                "updated_at": now,
                                "completed_at": now,
                                "error": error,
                            }
                        )
                        self._write_run_locked(updated)
                    continue
                if run.status != "running":
                    continue
                if run.current_step >= len(run.steps):
                    updated = run.model_copy(update={"status": "pending", "updated_at": now})
                    self._write_run_locked(updated)
                    recovered.append(run.id)
                    continue
                step = run.steps[run.current_step]
                if step.status != "running" or not step.attempts:
                    updated = run.model_copy(update={"status": "pending", "updated_at": now})
                    self._write_run_locked(updated)
                    recovered.append(run.id)
                    continue
                attempt = _active_attempt(step)
                if attempt.retry_safe:
                    definition_step = run.definition.steps[run.current_step]
                    retry = definition_step.retry or run.definition.defaults.retry
                    exhausted = len(step.attempts) >= retry.attempts
                    error = RunError(
                        category="retry_exhausted" if exhausted else "interrupted",
                        message=(
                            "workflow stopped after exhausting retry-safe step attempts"
                            if exhausted
                            else "workflow process stopped during a retry-safe step"
                        ),
                        retryable=not exhausted,
                    )
                    completed_attempt = attempt.model_copy(
                        update={"status": "failed", "completed_at": now, "error": error}
                    )
                    recovered_step = step.model_copy(
                        update={
                            "status": "failed" if exhausted else "pending",
                            "attempts": [*step.attempts[:-1], completed_attempt],
                            "completed_at": now if exhausted else None,
                            "error": error,
                        }
                    )
                    updated = _replace_step(run, run.current_step, recovered_step).model_copy(
                        update={
                            "status": "failed" if exhausted else "pending",
                            "updated_at": now,
                            "completed_at": now if exhausted else None,
                            "error": error if exhausted else None,
                        }
                    )
                    if not exhausted:
                        recovered.append(run.id)
                    else:
                        diagnostics.append(f"{run.id}: retry attempts exhausted during recovery")
                else:
                    error = RunError(
                        category="outcome_unknown",
                        message="workflow stopped during a non-retry-safe step",
                        outcome_unknown=True,
                    )
                    completed_attempt = attempt.model_copy(
                        update={
                            "status": "outcome_unknown",
                            "completed_at": now,
                            "error": error,
                        }
                    )
                    failed_step = step.model_copy(
                        update={
                            "status": "failed",
                            "attempts": [*step.attempts[:-1], completed_attempt],
                            "completed_at": now,
                            "error": error,
                        }
                    )
                    updated = _replace_step(run, run.current_step, failed_step).model_copy(
                        update={
                            "status": "failed",
                            "updated_at": now,
                            "completed_at": now,
                            "error": error,
                        }
                    )
                    unknown.append(run.id)
                self._write_run_locked(updated)
            index, rebuild_diagnostics = self._rebuild_index_locked()
            diagnostics.extend(rebuild_diagnostics)
            self._write_index_locked(index)
        return RecoveryResult(tuple(recovered), tuple(unknown), tuple(diagnostics))

    def rebuild_index(self) -> RecoveryResult:
        with exclusive_file_lock(self.lock_path):
            index, diagnostics = self._rebuild_index_locked()
            self._write_index_locked(index)
        return RecoveryResult((), (), tuple(diagnostics))

    def _checkpoint_locked(self, run: WorkflowRun) -> WorkflowRun:
        validated = WorkflowRun.model_validate(run.model_dump(mode="python"))
        self._write_run_locked(validated)
        index, _ = self._load_or_rebuild_index_locked()
        self._index_run(index, validated)
        self._write_index_locked(index)
        return validated

    def _write_run_locked(self, run: WorkflowRun) -> None:
        content = run.model_dump_json(indent=2, by_alias=True) + "\n"
        if len(content.encode("utf-8")) > MAX_RUN_BYTES:
            raise AutomationStoreError(f"workflow run {run.id} exceeds {MAX_RUN_BYTES} bytes")
        atomic_write_text(
            self._run_path(run.id),
            content,
            mode=0o600,
        )

    def _load_run_locked(self, run_id: str) -> WorkflowRun:
        try:
            return WorkflowRun.model_validate_json(
                self._read_bounded(self._run_path(run_id), MAX_RUN_BYTES, "workflow run")
            )
        except FileNotFoundError as exc:
            raise AutomationStoreError(f"workflow run not found: {run_id}") from exc
        except (OSError, ValidationError) as exc:
            raise AutomationStoreError(f"cannot load workflow run {run_id}: {exc}") from exc

    def _load_run_if_present_locked(self, run_id: str) -> WorkflowRun | None:
        if not run_id:
            return None
        path = self._run_path(run_id)
        if not path.exists():
            return None
        try:
            return self._load_run_locked(run_id)
        except AutomationStoreError as exc:
            raise AutomationStoreError(
                f"reservation points to unreadable workflow run {run_id}: {exc}"
            ) from exc

    def _find_run_locked(self, workflow_id: str, event_id: str) -> WorkflowRun | None:
        matches: list[WorkflowRun] = []
        for path in self.runs_dir.glob("run-*.json"):
            try:
                run = WorkflowRun.model_validate_json(
                    self._read_bounded(path, MAX_RUN_BYTES, "workflow run")
                )
            except (OSError, ValidationError, AutomationStoreError):
                continue
            if run.workflow_id == workflow_id and run.event.id == event_id:
                matches.append(run)
        if not matches:
            return None
        return min(matches, key=lambda run: (run.created_at, run.id))

    def _load_or_rebuild_index_locked(self) -> tuple[dict[str, Any], list[str]]:
        try:
            raw = json.loads(
                self._read_bounded(self.index_path, MAX_INDEX_BYTES, "automation index")
            )
            if raw.get("version") != 1 or not isinstance(raw.get("reservations"), dict):
                raise ValueError("invalid automation index shape")
            if not isinstance(raw.get("runs"), dict):
                raise ValueError("invalid automation index run summaries")
            return raw, []
        except FileNotFoundError:
            return self._rebuild_index_locked()
        except (OSError, json.JSONDecodeError, ValueError, AutomationStoreError):
            return self._rebuild_index_locked()

    def _rebuild_index_locked(self) -> tuple[dict[str, Any], list[str]]:
        index = _empty_index()
        diagnostics: list[str] = []
        reservations: dict[str, WorkflowRun] = {}
        for path in sorted(self.runs_dir.glob("run-*.json")):
            try:
                run = WorkflowRun.model_validate_json(
                    self._read_bounded(path, MAX_RUN_BYTES, "workflow run")
                )
            except (OSError, ValidationError, AutomationStoreError) as exc:
                diagnostics.append(f"{path.name}: {exc}")
                continue
            key = _reservation_key(run.workflow_id, run.event.id)
            existing = reservations.get(key)
            if existing is not None:
                winner = min(existing, run, key=lambda item: (item.created_at, item.id))
                loser = run if winner is existing else existing
                reservations[key] = winner
                diagnostics.append(
                    f"duplicate reservation {run.workflow_id!r}/{run.event.id!r}; "
                    f"kept {winner.id}, ignored {loser.id}"
                )
                continue
            reservations[key] = run
        for run in reservations.values():
            self._index_run(index, run)
        return index, diagnostics

    def _index_run(self, index: dict[str, Any], run: WorkflowRun) -> None:
        key = _reservation_key(run.workflow_id, run.event.id)
        index["reservations"][key] = {
            "workflow_id": run.workflow_id,
            "event_id": run.event.id,
            "run_id": run.id,
        }
        index["runs"][run.id] = {
            "workflow_id": run.workflow_id,
            "event_id": run.event.id,
            "status": run.status,
            "updated_at": run.updated_at.isoformat(),
        }

    def _write_index_locked(self, index: dict[str, Any]) -> None:
        atomic_write_text(
            self.index_path,
            json.dumps(index, indent=2, sort_keys=True) + "\n",
            mode=0o600,
        )

    def _run_path(self, run_id: str) -> Path:
        if not run_id.startswith("run-") or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in run_id):
            raise AutomationStoreError(f"invalid workflow run ID: {run_id!r}")
        return self.runs_dir / f"{run_id}.json"

    def _new_run_id(self) -> str:
        now = _utc(self._clock()).strftime("%Y%m%dT%H%M%S%fZ")
        return f"run-{now}-{uuid4().hex[:12]}"

    @staticmethod
    def _read_bounded(path: Path, limit: int, label: str) -> str:
        if path.stat().st_size > limit:
            raise AutomationStoreError(f"{label} {path.name} exceeds {limit} bytes")
        return path.read_text(encoding="utf-8")

    def _next_available_run_id_locked(self) -> str:
        for _ in range(10):
            run_id = self._id_factory()
            if not self._run_path(run_id).exists():
                return run_id
        raise AutomationStoreError("could not allocate a unique workflow run ID")


def _empty_index() -> dict[str, Any]:
    return {"version": 1, "reservations": {}, "runs": {}}


def _reservation_key(workflow_id: str, event_id: str) -> str:
    return hashlib.sha256(f"{workflow_id}\0{event_id}".encode("utf-8")).hexdigest()


def _verify_reservation(run: WorkflowRun, workflow_id: str, event_id: str) -> None:
    if run.workflow_id != workflow_id or run.event.id != event_id:
        raise AutomationStoreError("automation reservation hash collision or corrupt index")


def _step_by_id(run: WorkflowRun, step_id: str) -> tuple[int, StepRun]:
    for index, step in enumerate(run.steps):
        if step.id == step_id:
            return index, step
    raise TransitionError(f"workflow step not found: {step_id}")


def _replace_step(run: WorkflowRun, index: int, step: StepRun) -> WorkflowRun:
    steps = list(run.steps)
    steps[index] = step
    return run.model_copy(update={"steps": steps})


def _active_attempt(step: StepRun) -> StepAttempt:
    if not step.attempts or step.attempts[-1].status != "running":
        raise TransitionError(f"step {step.id!r} has no active attempt")
    return step.attempts[-1]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AutomationStoreError("automation store clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)
