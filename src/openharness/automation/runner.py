"""Sequential durable execution for validated automation workflows."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from openharness.automation.actions import (
    ActionExecutionContext,
    ActionRegistry,
    ActionResult,
    PreparedAction,
)
from openharness.automation.concurrency import WorkflowConcurrencyCoordinator
from openharness.automation.matcher import evaluate_condition, match_workflow
from openharness.automation.models import (
    ActionStep,
    AgentStep,
    ApprovalStep,
    AutomationEvent,
    WorkflowDefinition,
    validate_json_value,
)
from openharness.automation.state import RunError, WorkflowRun
from openharness.automation.store import AutomationStore, ReservationResult
from openharness.automation.templates import TemplateRenderError, render_template
from openharness.tools.executor import GovernedToolExecutor


class WorkflowNotMatchedError(ValueError):
    """Raised when direct submission does not satisfy a workflow trigger."""


@dataclass(frozen=True)
class AgentStepResult:
    """Bounded structured outcome returned by an isolated skill agent."""

    output: dict[str, Any] | None = None
    is_error: bool = False
    error_category: str = "agent_error"
    error_message: str = ""
    retryable: bool = False
    outcome_unknown: bool = False

    def __post_init__(self) -> None:
        """Reject non-JSON, oversized, or contradictory agent outcomes."""

        if self.output is not None:
            validate_json_value(self.output, path="agent step output")
            encoded = json.dumps(
                self.output,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            if len(encoded) > 256 * 1024:
                raise ValueError("agent step output exceeds 262144 bytes")
        if not self.is_error and (self.retryable or self.outcome_unknown):
            raise ValueError("successful agent results cannot be retryable or outcome_unknown")


class AgentStepExecutor(Protocol):
    """Host contract for executing one bounded named-skill agent step."""

    def is_retry_safe(self, step: AgentStep) -> bool:
        """Return whether an interrupted execution can be replayed safely."""

        ...

    async def execute(
        self,
        step: AgentStep,
        run: WorkflowRun,
        *,
        invocation_id: str,
    ) -> AgentStepResult:
        """Execute one skill step using the supplied stable attempt identity."""

        ...


@dataclass(frozen=True)
class RunnerResult:
    """Execution result paired with whether intake created the durable run."""

    run: WorkflowRun
    created: bool


ToolExecutorFactory = Callable[[WorkflowRun], GovernedToolExecutor | None]
Sleep = Callable[[float], Awaitable[None]]
logger = logging.getLogger(__name__)


class WorkflowRunner:
    """Run sequential action, agent, and approval steps with durable checkpoints.

    Integration: The runner owns orchestration while ``AutomationStore`` owns
    every state transition and hosts inject actions, agents, governed tools, and
    concurrency coordination.

    Event loop: Blocking store operations are offloaded with ``to_thread``;
    action, agent, timeout, cancellation, and backoff waits stay on the caller's
    loop.

    Change safety: Checkpoint before every effect, never replay an uncertain
    non-retry-safe attempt automatically, and preserve declaration order.
    """

    def __init__(
        self,
        *,
        store: AutomationStore,
        actions: ActionRegistry,
        agent_executor: AgentStepExecutor | None = None,
        tool_executor_factory: ToolExecutorFactory | None = None,
        concurrency: WorkflowConcurrencyCoordinator | None = None,
        sleeper: Sleep = asyncio.sleep,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Bind durable state, host capabilities, and loop-local coordinators."""

        self.store = store
        self.actions = actions
        self.agent_executor = agent_executor
        self.tool_executor_factory = tool_executor_factory
        self.concurrency = concurrency or WorkflowConcurrencyCoordinator()
        self._run_concurrency = WorkflowConcurrencyCoordinator()
        self.sleeper = sleeper
        self.metadata = metadata or {}
        self._cancellation_directives: dict[str, tuple[bool, str | None]] = {}

    def prepare_cancellation(
        self,
        run_id: str,
        *,
        preserve_for_recovery: bool = False,
        reason: str | None = None,
    ) -> None:
        """Describe how the next task cancellation for a run should be checkpointed."""

        self._cancellation_directives[run_id] = (preserve_for_recovery, reason)

    async def submit(
        self,
        definition: WorkflowDefinition,
        event: AutomationEvent,
    ) -> ReservationResult:
        """Match, render concurrency identity, and reserve an event before execution."""

        trace = match_workflow(definition, event)
        if not trace.matched:
            raise WorkflowNotMatchedError(
                f"event {event.id!r} does not match workflow {definition.id!r}"
            )
        concurrency_key = None
        if definition.concurrency is not None:
            rendered = render_template(
                definition.concurrency.key,
                _template_context(event=event),
            )
            if not isinstance(rendered, str) or not rendered.strip():
                raise TemplateRenderError("concurrency key must render to a non-empty string")
            concurrency_key = rendered
        reservation = await asyncio.to_thread(
            self.store.reserve,
            definition,
            event,
            concurrency_key=concurrency_key,
        )
        logger.info(
            "automation run reserved workflow_id=%s run_id=%s event_id=%s created=%s",
            definition.id,
            reservation.run.id,
            event.id,
            reservation.created,
        )
        return reservation

    async def run_event(
        self,
        definition: WorkflowDefinition,
        event: AutomationEvent,
    ) -> RunnerResult:
        """Reserve and execute a newly created run, leaving duplicates untouched."""

        reservation = await self.submit(definition, event)
        if not reservation.created:
            return RunnerResult(reservation.run, False)
        return RunnerResult(await self.execute(reservation.run.id), True)

    async def execute(self, run_id: str) -> WorkflowRun:
        """Execute or resume one run under per-run and rendered-key coordination.

        Task cancellation normally checkpoints the run as cancelled. Service
        shutdown may predeclare recovery preservation so startup recovery can
        classify the interrupted attempt instead.
        """

        try:
            async with self._run_concurrency.slot(run_id, "serialize"):
                run = await asyncio.to_thread(self.store.load_run, run_id)
                if run.status in {"completed", "failed", "cancelled", "waiting_approval"}:
                    return run
                policy = (
                    run.definition.concurrency.policy
                    if run.definition.concurrency
                    else "serialize"
                )
                key = run.concurrency_key or ""
                async with self.concurrency.slot(key, policy) as lease:
                    if not lease.acquired:
                        return await asyncio.to_thread(
                            self.store.cancel_run,
                            run.id,
                            reason=lease.reason or "concurrency policy dropped this run",
                        )
                    return await self._execute_steps(run.id)
        except asyncio.CancelledError:
            preserve, reason = self._cancellation_directives.pop(run_id, (False, None))
            if not preserve:
                latest = await asyncio.to_thread(self.store.load_run, run_id)
                if latest.status in {"pending", "running", "waiting_approval"}:
                    await asyncio.to_thread(
                        self.store.cancel_run,
                        run_id,
                        reason=reason or "workflow task was cancelled",
                    )
            raise
        finally:
            self._cancellation_directives.pop(run_id, None)

    async def _execute_steps(self, run_id: str) -> WorkflowRun:
        """Advance sequential steps until completion, failure, or approval wait."""

        while True:
            run = await asyncio.to_thread(self.store.load_run, run_id)
            if run.status in {"completed", "failed", "cancelled", "waiting_approval"}:
                return run
            if run.current_step >= len(run.steps):
                if run.status == "pending":
                    run = await asyncio.to_thread(self.store.transition_run, run.id, "running")
                completed = await asyncio.to_thread(
                    self.store.transition_run,
                    run.id,
                    "completed",
                )
                logger.info(
                    "automation run completed workflow_id=%s run_id=%s event_id=%s",
                    run.workflow_id,
                    run.id,
                    run.event.id,
                )
                return completed
            now = await asyncio.to_thread(self.store.now)
            elapsed = (now - run.created_at).total_seconds()
            if elapsed >= run.definition.defaults.max_run_seconds:
                step = run.definition.steps[run.current_step]
                return await self._fail_pending(
                    run,
                    step.id,
                    "run_duration_exceeded",
                    (
                        "workflow exceeded its maximum duration of "
                        f"{run.definition.defaults.max_run_seconds} seconds"
                    ),
                )
            if run.status == "pending":
                run = await asyncio.to_thread(self.store.transition_run, run.id, "running")

            step_definition = run.definition.steps[run.current_step]
            logger.info(
                "automation step evaluating workflow_id=%s run_id=%s event_id=%s step_id=%s step_type=%s",
                run.workflow_id,
                run.id,
                run.event.id,
                step_definition.id,
                step_definition.type,
            )
            if step_definition.when is not None:
                matched, _ = evaluate_condition(step_definition.when, _template_context(run=run))
                if not matched:
                    await asyncio.to_thread(self.store.skip_step, run.id, step_definition.id)
                    continue

            if isinstance(step_definition, ApprovalStep):
                try:
                    prompt = render_template(step_definition.prompt, _template_context(run=run))
                    if not isinstance(prompt, str) or not prompt.strip():
                        raise TemplateRenderError("approval prompt must render to non-empty text")
                except TemplateRenderError as exc:
                    return await self._fail_pending(run, step_definition.id, "template_error", str(exc))
                return await asyncio.to_thread(
                    self.store.wait_for_approval,
                    run.id,
                    step_definition.id,
                    prompt=prompt,
                )
            if isinstance(step_definition, ActionStep):
                result = await self._execute_action_step(run, step_definition)
            else:
                result = await self._execute_agent_step(run, step_definition)
            if result.status == "failed":
                return result

    async def _execute_action_step(self, run: WorkflowRun, step: ActionStep) -> WorkflowRun:
        """Render and prepare an action before any attempt checkpoint or effect."""

        if step.action not in run.definition.policy.allowed_actions:
            return await self._fail_pending(
                run,
                step.id,
                "action_policy_denied",
                f"action {step.action!r} is not allowed by the workflow",
            )
        try:
            rendered = render_template(step.arguments, _template_context(run=run))
            if not isinstance(rendered, dict):
                raise TemplateRenderError("action arguments must render to an object")
            prepared = self.actions.prepare(step.action, rendered)
        except Exception as exc:
            return await self._fail_pending(run, step.id, "action_validation", str(exc))
        return await self._attempt_action(run, step, prepared, rendered)

    async def _attempt_action(
        self,
        run: WorkflowRun,
        step: ActionStep,
        prepared: PreparedAction,
        rendered: dict[str, Any],
    ) -> WorkflowRun:
        """Checkpoint, time-bound, execute, and normalize one action attempt."""

        started = await asyncio.to_thread(
            self.store.start_step,
            run.id,
            step.id,
            input=rendered,
            retry_safe=prepared.retry_safe,
        )
        attempt = started.steps[started.current_step].attempts[-1]
        context = ActionExecutionContext(
            run=started,
            step_id=step.id,
            logical_idempotency_key=attempt.logical_idempotency_key,
            attempt_idempotency_key=attempt.attempt_idempotency_key,
            allowed_tools=frozenset(started.definition.policy.allowed_tools),
            governed_tool_executor=(
                self.tool_executor_factory(started) if self.tool_executor_factory else None
            ),
            metadata=dict(self.metadata),
        )
        step_timeout = step.timeout_seconds or started.definition.defaults.timeout_seconds
        timeout, duration_limited = await self._remaining_timeout(started, step_timeout)
        if timeout <= 0:
            result = ActionResult(
                is_error=True,
                error_category="run_duration_exceeded",
                error_message="workflow exceeded its maximum duration",
                retryable=False,
                outcome_unknown=False,
            )
            return await self._finish_attempt(started, step, result)
        try:
            result = await asyncio.wait_for(
                self.actions.execute(prepared, context),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            result = ActionResult(
                is_error=True,
                error_category=("run_duration_exceeded" if duration_limited else "timeout"),
                error_message=(
                    "workflow exceeded its maximum duration"
                    if duration_limited
                    else f"action timed out after {timeout} seconds"
                ),
                retryable=prepared.retry_safe and not duration_limited,
                outcome_unknown=not prepared.retry_safe,
            )
        except Exception as exc:
            result = ActionResult(
                is_error=True,
                error_category="action_exception",
                error_message=f"{type(exc).__name__}: {exc}",
                retryable=False,
                outcome_unknown=not prepared.retry_safe,
            )
        if result.retryable and not prepared.retry_safe:
            result = ActionResult(
                output=result.output,
                is_error=result.is_error,
                error_category=result.error_category,
                error_message=result.error_message,
                retryable=False,
                outcome_unknown=result.outcome_unknown,
                metadata=result.metadata,
            )
        return await self._finish_attempt(started, step, result)

    async def _execute_agent_step(self, run: WorkflowRun, step: AgentStep) -> WorkflowRun:
        """Run a bounded skill agent and validate its declared structured output."""

        if self.agent_executor is None:
            return await self._fail_pending(
                run,
                step.id,
                "agent_unavailable",
                "agent step execution is unavailable in this host",
            )
        retry_safe = self.agent_executor.is_retry_safe(step)
        started = await asyncio.to_thread(
            self.store.start_step,
            run.id,
            step.id,
            input={"skill": step.skill, "allowed_tools": step.allowed_tools},
            retry_safe=retry_safe,
        )
        attempt = started.steps[started.current_step].attempts[-1]
        step_timeout = step.timeout_seconds or started.definition.defaults.timeout_seconds
        timeout, duration_limited = await self._remaining_timeout(started, step_timeout)
        if timeout <= 0:
            agent_result = AgentStepResult(
                is_error=True,
                error_category="run_duration_exceeded",
                error_message="workflow exceeded its maximum duration",
                retryable=False,
                outcome_unknown=False,
            )
            result = ActionResult(
                is_error=True,
                error_category=agent_result.error_category,
                error_message=agent_result.error_message,
                outcome_unknown=agent_result.outcome_unknown,
            )
            return await self._finish_attempt(started, step, result)
        try:
            agent_result = await asyncio.wait_for(
                self.agent_executor.execute(
                    step,
                    started,
                    invocation_id=attempt.attempt_idempotency_key,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            agent_result = AgentStepResult(
                is_error=True,
                error_category=("run_duration_exceeded" if duration_limited else "timeout"),
                error_message=(
                    "workflow exceeded its maximum duration"
                    if duration_limited
                    else f"agent step timed out after {timeout} seconds"
                ),
                retryable=retry_safe and not duration_limited,
                outcome_unknown=not retry_safe,
            )
        except Exception as exc:
            agent_result = AgentStepResult(
                is_error=True,
                error_category="agent_exception",
                error_message=f"{type(exc).__name__}: {exc}",
                retryable=False,
                outcome_unknown=not retry_safe,
            )
        if not agent_result.is_error:
            try:
                output = validate_agent_output(step, agent_result.output)
            except ValueError as exc:
                agent_result = AgentStepResult(
                    is_error=True,
                    error_category="invalid_agent_output",
                    error_message=str(exc),
                    retryable=retry_safe,
                )
            else:
                completed = await asyncio.to_thread(
                    self.store.complete_step,
                    started.id,
                    step.id,
                    output=output,
                )
                logger.info(
                    "automation step completed workflow_id=%s run_id=%s event_id=%s step_id=%s",
                    started.workflow_id,
                    started.id,
                    started.event.id,
                    step.id,
                )
                return completed
        if agent_result.retryable and not retry_safe:
            agent_result = AgentStepResult(
                output=agent_result.output,
                is_error=agent_result.is_error,
                error_category=agent_result.error_category,
                error_message=agent_result.error_message,
                retryable=False,
                outcome_unknown=agent_result.outcome_unknown,
            )
        result = ActionResult(
            is_error=True,
            error_category=agent_result.error_category,
            error_message=agent_result.error_message,
            retryable=agent_result.retryable,
            outcome_unknown=agent_result.outcome_unknown,
        )
        return await self._finish_attempt(started, step, result)

    async def _finish_attempt(
        self,
        run: WorkflowRun,
        step: ActionStep | AgentStep,
        result: ActionResult,
    ) -> WorkflowRun:
        """Checkpoint success or failure and schedule only permitted retries."""

        if not result.is_error:
            completed = await asyncio.to_thread(
                self.store.complete_step,
                run.id,
                step.id,
                output=result.output,
            )
            logger.info(
                "automation step completed workflow_id=%s run_id=%s event_id=%s step_id=%s",
                run.workflow_id,
                run.id,
                run.event.id,
                step.id,
            )
            return completed
        error = RunError(
            category=result.error_category,
            message=(result.error_message or result.error_category)[:4000],
            retryable=result.retryable,
            outcome_unknown=result.outcome_unknown,
        )
        failed = await asyncio.to_thread(
            self.store.fail_step,
            run.id,
            step.id,
            error=error,
            outcome_unknown=result.outcome_unknown,
        )
        logger.warning(
            "automation step failed workflow_id=%s run_id=%s event_id=%s step_id=%s category=%s retryable=%s outcome_unknown=%s",
            run.workflow_id,
            run.id,
            run.event.id,
            step.id,
            result.error_category,
            result.retryable,
            result.outcome_unknown,
        )
        retry = step.retry or failed.definition.defaults.retry
        attempts = len(failed.steps[failed.current_step].attempts)
        if result.retryable and not result.outcome_unknown and attempts < retry.attempts:
            pending = await asyncio.to_thread(
                self.store.retry_run,
                failed.id,
                operator_override=False,
            )
            delay = retry_delay(retry.backoff_seconds, attempts)
            if delay > 0:
                await self.sleeper(delay)
            return pending
        return failed

    async def _fail_pending(
        self,
        run: WorkflowRun,
        step_id: str,
        category: str,
        message: str,
    ) -> WorkflowRun:
        """Fail before an external attempt when validation or setup is impossible."""

        failed = await asyncio.to_thread(
            self.store.fail_pending_step,
            run.id,
            step_id,
            error=RunError(category=category, message=(message or category)[:4000]),
        )
        logger.warning(
            "automation step failed workflow_id=%s run_id=%s event_id=%s step_id=%s category=%s",
            run.workflow_id,
            run.id,
            run.event.id,
            step_id,
            category,
        )
        return failed

    async def _remaining_timeout(
        self,
        run: WorkflowRun,
        step_timeout: int,
    ) -> tuple[float, bool]:
        """Intersect the step timeout with the workflow's remaining lifetime."""

        now = await asyncio.to_thread(self.store.now)
        elapsed = max(0.0, (now - run.created_at).total_seconds())
        remaining = max(0.0, run.definition.defaults.max_run_seconds - elapsed)
        return min(float(step_timeout), remaining), remaining <= step_timeout


def _template_context(
    *,
    event: AutomationEvent | None = None,
    run: WorkflowRun | None = None,
) -> dict[str, Any]:
    """Build the only event/run/step data visible to conditions and templates."""

    selected_event = event or (run.event if run is not None else None)
    return {
        "event": selected_event.model_dump(mode="json") if selected_event else {},
        "run": run.model_dump(mode="json") if run else {},
        "steps": dict((run.context.get("steps") or {}) if run else {}),
    }


def retry_delay(backoff: list[float], attempts_completed: int) -> float:
    """Select the bounded delay for the next attempt, repeating the last value."""

    if not backoff:
        return 0
    index = min(max(0, attempts_completed - 1), len(backoff) - 1)
    return backoff[index]


def validate_agent_output(step: AgentStep, output: dict[str, Any] | None) -> dict[str, Any]:
    """Validate exact fields and primitive JSON types against an agent-step schema."""

    if not isinstance(output, dict):
        raise ValueError("agent output must be a JSON object")
    try:
        output = validate_json_value(output, path="agent output")
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    unknown = set(output) - set(step.output_schema)
    if unknown:
        raise ValueError(f"agent output contains unknown fields: {', '.join(sorted(unknown))}")
    for name, field in step.output_schema.items():
        if field.required and name not in output:
            raise ValueError(f"agent output is missing required field {name!r}")
        if name not in output:
            continue
        value = output[name]
        valid = {
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
        }[field.type]
        if not valid:
            raise ValueError(f"agent output field {name!r} must be {field.type}")
    return output
