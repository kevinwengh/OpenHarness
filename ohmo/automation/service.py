"""Ohmo automation discovery, admission dispatch, execution, and recovery lifecycle."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from openharness.automation.actions import ActionRegistry
from openharness.automation.loader import DefinitionDiagnostic, load_workflow_definitions
from openharness.automation.matcher import match_workflow
from openharness.automation.models import AgentStep, AutomationEvent, WorkflowDefinition
from openharness.automation.runner import AgentStepExecutor, WorkflowRunner
from openharness.automation.store import AutomationStore
from openharness.channels.bus.events import InboundMessage
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
            cancel_on_task_cancel=False,
        )
        self.definitions: tuple[WorkflowDefinition, ...] = ()
        self.diagnostics: tuple[DefinitionDiagnostic, ...] = ()
        self._tasks: dict[str, asyncio.Task] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        loaded = await asyncio.to_thread(
            load_workflow_definitions,
            get_automations_dir(self.workspace),
        )
        definitions, preflight = await self._preflight(loaded.definitions)
        self.definitions = definitions
        self.diagnostics = (*loaded.diagnostics, *preflight)
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
        self._started = True
        pending = await asyncio.to_thread(self.store.list_runs, status="pending")
        for run in pending:
            self._schedule(run.id)

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._started = False

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

    async def drain(self) -> None:
        """Wait until currently scheduled runs finish; intended for shutdown and tests."""

        while self._tasks:
            await asyncio.gather(*tuple(self._tasks.values()), return_exceptions=True)

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
            self.runner.execute(run_id),
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


def _combined_source_behavior(definitions: tuple[WorkflowDefinition, ...]) -> str:
    behaviors = {definition.source_behavior for definition in definitions}
    if "silent" in behaviors:
        return "silent"
    if "consume" in behaviors:
        return "consume"
    return "continue"
