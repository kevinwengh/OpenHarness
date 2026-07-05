"""Ohmo automation discovery, admission dispatch, execution, and recovery lifecycle."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from openharness.automation.actions import ActionRegistry
from openharness.automation.loader import DefinitionDiagnostic, load_workflow_definitions
from openharness.automation.matcher import match_workflow
from openharness.automation.models import (
    AgentStep,
    ApprovalStep,
    AutomationEvent,
    WorkflowDefinition,
)
from openharness.automation.runner import AgentStepExecutor, WorkflowRunner
from openharness.automation.state import TransitionError
from openharness.automation.store import AutomationStore, AutomationStoreError
from openharness.channels.bus.events import InboundMessage, OutboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.config.settings import load_settings
from openharness.plugins.loader import load_plugins

from ohmo.automation.actions import ChannelSendAction, KnowledgeUpsertAction
from ohmo.automation.agent import RuntimeSkillAgentExecutor
from ohmo.automation.events import channel_message_event
from ohmo.workspace import (
    get_automation_state_dir,
    get_automations_dir,
    get_plugins_dir,
    initialize_workspace,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutomationDispatch:
    source_behavior: str = "continue"
    workflow_ids: tuple[str, ...] = ()
    run_ids: tuple[str, ...] = ()
    created_run_ids: tuple[str, ...] = ()

    @property
    def continue_to_assistant(self) -> bool:
        return self.source_behavior == "continue"


class OhmoAutomationService:
    """Own workflow definitions and background run tasks for one Ohmo gateway."""

    def __init__(
        self,
        *,
        workspace: str | Path,
        cwd: str | Path,
        bus: MessageBus,
        provider_profile: str | None = None,
        actions: ActionRegistry | None = None,
        agent_executor: AgentStepExecutor | None = None,
        maintenance_interval_seconds: float = 5.0,
    ) -> None:
        self.workspace = initialize_workspace(workspace)
        self.cwd = Path(cwd).expanduser().resolve()
        self.bus = bus
        self.actions = actions or ActionRegistry()
        if self.actions.get(ChannelSendAction.name) is None:
            self.actions.register(ChannelSendAction(bus, self.workspace))
        if self.actions.get(KnowledgeUpsertAction.name) is None:
            self.actions.register(KnowledgeUpsertAction(self.workspace))
        for plugin in load_plugins(
            load_settings(),
            self.cwd,
            extra_roots=(get_plugins_dir(self.workspace),),
        ):
            if not plugin.enabled:
                continue
            for action in plugin.automation_actions:
                if self.actions.get(action.name) is not None:
                    logger.warning(
                        "ohmo automation plugin action ignored plugin=%s action=%s reason=duplicate",
                        plugin.name,
                        action.name,
                    )
                    continue
                self.actions.register(action)
        self.agent_executor = agent_executor or RuntimeSkillAgentExecutor(
            workspace=self.workspace,
            cwd=self.cwd,
            provider_profile=provider_profile,
        )
        self.store = AutomationStore(get_automation_state_dir(self.workspace))
        self.runner = WorkflowRunner(
            store=self.store,
            actions=self.actions,
            agent_executor=self.agent_executor,
        )
        self.definitions: tuple[WorkflowDefinition, ...] = ()
        self.diagnostics: tuple[DefinitionDiagnostic, ...] = ()
        self._tasks: dict[str, asyncio.Task] = {}
        if maintenance_interval_seconds <= 0:
            raise ValueError("maintenance interval must be positive")
        self._maintenance_interval_seconds = maintenance_interval_seconds
        self._maintenance_task: asyncio.Task | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self.validate_configuration()
        for diagnostic in self.diagnostics:
            logger.warning(
                "ohmo automation definition ignored path=%s workflow=%s reason=%s",
                diagnostic.path,
                diagnostic.workflow_id or "",
                diagnostic.message,
            )

        recovery = await asyncio.to_thread(self.store.recover)
        for diagnostic in recovery.diagnostics:
            logger.warning("ohmo automation recovery diagnostic: %s", diagnostic)
        await asyncio.to_thread(self.store.expire_waiting_runs)
        retention = await asyncio.to_thread(self.store.prune)
        for diagnostic in retention.diagnostics:
            logger.warning("ohmo automation retention diagnostic: %s", diagnostic)
        self._started = True
        self._maintenance_task = asyncio.create_task(
            self._maintenance_loop(),
            name="ohmo-automation-maintenance",
        )
        pending = await asyncio.to_thread(self.store.list_runs, status="pending")
        waiting = await asyncio.to_thread(self.store.list_runs, status="waiting_approval")
        for run in (*pending, *waiting):
            self._schedule(run.id)

    async def validate_configuration(self) -> None:
        """Load and capability-check definitions without recovering or executing runs."""

        loaded = await asyncio.to_thread(
            load_workflow_definitions,
            get_automations_dir(self.workspace),
        )
        definitions, preflight = await self._preflight(loaded.definitions)
        self.definitions = definitions
        self.diagnostics = (*loaded.diagnostics, *preflight)

    async def stop(self) -> None:
        maintenance = self._maintenance_task
        self._maintenance_task = None
        if maintenance is not None:
            maintenance.cancel()
            await asyncio.gather(maintenance, return_exceptions=True)
        tasks = list(self._tasks.values())
        for run_id, task in list(self._tasks.items()):
            if task.done():
                continue
            self.runner.prepare_cancellation(run_id, preserve_for_recovery=True)
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._started = False

    async def _maintenance_loop(self) -> None:
        while True:
            await asyncio.sleep(self._maintenance_interval_seconds)
            try:
                expired = await asyncio.to_thread(self.store.expire_waiting_runs)
                for run_id in expired:
                    logger.info("automation waiting run expired run_id=%s", run_id)
                await asyncio.to_thread(self.store.prune)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ohmo automation maintenance failed")

    async def dispatch_message(self, message: InboundMessage) -> AutomationDispatch:
        return await self.dispatch_event(channel_message_event(message))

    async def dispatch_event(self, event: AutomationEvent) -> AutomationDispatch:
        if not self._started:
            await self.start()
        matched = tuple(
            definition
            for definition in self.definitions
            if match_workflow(definition, event).matched
        )
        if not matched:
            return AutomationDispatch()

        run_ids: list[str] = []
        created: list[str] = []
        for definition in matched:
            reservation = await self.runner.submit(definition, event)
            run_ids.append(reservation.run.id)
            if reservation.created:
                created.append(reservation.run.id)
                self._schedule(reservation.run.id)
        return AutomationDispatch(
            source_behavior=_combined_source_behavior(matched),
            workflow_ids=tuple(definition.id for definition in matched),
            run_ids=tuple(run_ids),
            created_run_ids=tuple(created),
        )

    async def submit_workflow(
        self,
        workflow_id: str,
        event: AutomationEvent,
    ) -> AutomationDispatch:
        if not self._started:
            await self.start()
        definition = next(
            (item for item in self.definitions if item.id == workflow_id),
            None,
        )
        if definition is None:
            raise ValueError(f"automation workflow not found or failed preflight: {workflow_id}")
        reservation = await self.runner.submit(definition, event)
        if reservation.created:
            self._schedule(reservation.run.id)
        return AutomationDispatch(
            source_behavior=definition.source_behavior,
            workflow_ids=(definition.id,),
            run_ids=(reservation.run.id,),
            created_run_ids=(reservation.run.id,) if reservation.created else (),
        )

    async def retry_run(
        self,
        run_id: str,
        *,
        allow_unknown_outcome: bool = False,
    ):
        run = await asyncio.to_thread(
            self.store.retry_run,
            run_id,
            allow_unknown_outcome=allow_unknown_outcome,
        )
        self._schedule(run.id)
        return run

    async def cancel_run(self, run_id: str, *, reason: str):
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            self.runner.prepare_cancellation(run_id, reason=reason)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            run = await asyncio.to_thread(self.store.load_run, run_id)
            if run.status == "cancelled":
                return run
        return await asyncio.to_thread(self.store.cancel_run, run_id, reason=reason)

    async def resolve_approval(
        self,
        run_id: str,
        *,
        actor_id: str,
        approved: bool,
        reason: str | None = None,
    ):
        current = await asyncio.to_thread(self.store.load_run, run_id)
        delivery_task = self._tasks.get(run_id)
        if (
            current.status == "waiting_approval"
            and delivery_task is not None
            and not delivery_task.done()
        ):
            await asyncio.gather(delivery_task, return_exceptions=True)
        run = await asyncio.to_thread(
            self.store.resolve_approval,
            run_id,
            actor_id=actor_id,
            approved=approved,
            reason=reason,
        )
        if run.status == "pending":
            self._schedule(run.id)
        return run

    async def handle_gateway_command(self, message: InboundMessage) -> str | None:
        parts = message.content.strip().split(maxsplit=3)
        if len(parts) < 3 or parts[0].lower() != "/automation":
            return None
        operation = parts[1].lower()
        if operation not in {"approve", "reject"}:
            return None
        run_id = parts[2]
        reason = parts[3] if len(parts) == 4 else None
        try:
            run = await self.resolve_approval(
                run_id,
                actor_id=str(message.sender_id),
                approved=operation == "approve",
                reason=reason,
            )
        except (AutomationStoreError, TransitionError, ValueError) as exc:
            return f"Automation {operation} failed for {run_id}: {exc}"
        except Exception:
            logger.exception("ohmo approval command failed run_id=%s", run_id)
            return f"Automation {operation} failed for {run_id}."
        return f"Automation run {run.id} {run.approvals[-1].status}."

    async def drain(self) -> None:
        """Wait until currently scheduled runs finish; intended for shutdown and tests."""

        while self._tasks:
            await asyncio.gather(*tuple(self._tasks.values()), return_exceptions=True)

    def status_counts(self) -> dict[str, int]:
        runs = self.store.list_runs()
        return {
            "loaded": len(self.definitions),
            "invalid": len(self.diagnostics),
            "active": sum(run.status in {"pending", "running"} for run in runs),
            "waiting": sum(run.status == "waiting_approval" for run in runs),
            "failed": sum(run.status == "failed" for run in runs),
        }

    async def _preflight(
        self,
        definitions: tuple[WorkflowDefinition, ...],
    ) -> tuple[tuple[WorkflowDefinition, ...], tuple[DefinitionDiagnostic, ...]]:
        accepted: list[WorkflowDefinition] = []
        diagnostics: list[DefinitionDiagnostic] = []
        validate_skill = getattr(self.agent_executor, "validate_skill", None)
        for definition in definitions:
            missing_actions = sorted(
                {
                    step.action
                    for step in definition.steps
                    if hasattr(step, "action") and self.actions.get(step.action) is None
                }
            )
            errors = [f"unknown automation actions: {', '.join(missing_actions)}"] if missing_actions else []
            if self.agent_executor is None and any(
                isinstance(step, AgentStep) for step in definition.steps
            ):
                errors.append("agent execution is unavailable")
            elif validate_skill is not None:
                for step in definition.steps:
                    if not isinstance(step, AgentStep):
                        continue
                    error = await validate_skill(step.skill)
                    if error:
                        errors.append(error)
            if errors:
                diagnostics.append(
                    DefinitionDiagnostic(
                        get_automations_dir(self.workspace),
                        "; ".join(dict.fromkeys(errors)),
                        definition.id,
                    )
                )
            else:
                accepted.append(definition)
        return tuple(accepted), tuple(diagnostics)

    def _schedule(self, run_id: str) -> None:
        current = self._tasks.get(run_id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(
            self._execute_run(run_id),
            name=f"ohmo-automation:{run_id}",
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda finished, key=run_id: self._task_finished(key, finished))

    def _task_finished(self, run_id: str, task: asyncio.Task) -> None:
        if self._tasks.get(run_id) is task:
            self._tasks.pop(run_id, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "ohmo automation run crashed run_id=%s error=%s: %s",
                run_id,
                type(error).__name__,
                error,
            )

    async def _execute_run(self, run_id: str):
        run = await self.runner.execute(run_id)
        if run.status == "waiting_approval":
            await self._deliver_approval(run)
            run = await asyncio.to_thread(self.store.load_run, run.id)
        retention = await asyncio.to_thread(self.store.prune)
        for diagnostic in retention.diagnostics:
            logger.warning("ohmo automation retention diagnostic: %s", diagnostic)
        return run

    async def _deliver_approval(self, run) -> None:
        approval = run.approvals[-1]
        if approval.notification_sent_at is not None:
            return
        step = run.definition.steps[run.current_step]
        if not isinstance(step, ApprovalStep):
            raise RuntimeError("waiting approval run does not reference an approval step")
        target = step.target
        channel = target.channel if target else run.event.source.channel
        chat_id = target.chat_id if target else run.event.subject.chat_id
        thread_id = target.thread_id if target else run.event.subject.thread_id
        if not channel or not chat_id:
            if run.event.source.adapter == "cli":
                await asyncio.to_thread(self.store.mark_approval_notified, run.id)
                return
            raise RuntimeError("approval request has no notification target")
        metadata: dict[str, object] = {
            "_automation": {
                "generated": True,
                "run_id": run.id,
                "workflow_id": run.workflow_id,
                "ancestry": [*run.event.ancestry, run.event.id, run.id][-16:],
            }
        }
        if thread_id:
            metadata["thread_id"] = thread_id
            if channel == "slack":
                metadata["slack"] = {"thread_ts": thread_id}
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=(
                    f"Approval required for automation run {run.id}:\n"
                    f"{approval.prompt}\n\n"
                    f"Approve: /automation approve {run.id}\n"
                    f"Reject: /automation reject {run.id} [reason]"
                ),
                metadata=metadata,
            )
        )
        await asyncio.to_thread(self.store.mark_approval_notified, run.id)


def _combined_source_behavior(definitions: tuple[WorkflowDefinition, ...]) -> str:
    behaviors = {definition.source_behavior for definition in definitions}
    if "silent" in behaviors:
        return "silent"
    if "consume" in behaviors:
        return "consume"
    return "continue"
