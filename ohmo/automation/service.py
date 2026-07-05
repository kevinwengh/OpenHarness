"""Ohmo automation discovery, admission dispatch, execution, and recovery lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from openharness.api.client import SupportsStreamingMessages
from openharness.automation.actions import ActionRegistry, GovernedToolAction
from openharness.automation.loader import DefinitionDiagnostic, load_workflow_definitions
from openharness.automation.matcher import match_workflow
from openharness.automation.models import (
    ActionStep,
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
from openharness.permissions import PermissionChecker
from openharness.plugins.loader import load_plugins
from openharness.tools.executor import GovernedToolExecutor
from openharness.ui.runtime import RuntimeBundle, build_runtime, close_runtime

from ohmo.automation.actions import ChannelSendAction, KnowledgeUpsertAction
from ohmo.automation.agent import RuntimeSkillAgentExecutor, automation_permission_settings
from ohmo.automation.events import bounded_event_ancestry, channel_message_event
from ohmo.workspace import (
    get_automation_state_dir,
    get_automations_dir,
    get_memory_dir,
    get_plugins_dir,
    get_sessions_dir,
    get_skills_dir,
    initialize_workspace,
)

logger = logging.getLogger(__name__)
ToolRuntimeBuilder = Callable[[tuple[str, ...]], Awaitable[RuntimeBundle]]


@dataclass(frozen=True)
class AutomationDispatch:
    """Immediate bridge decision plus durable workflow/run identities."""

    source_behavior: str = "continue"
    workflow_ids: tuple[str, ...] = ()
    run_ids: tuple[str, ...] = ()
    created_run_ids: tuple[str, ...] = ()

    @property
    def continue_to_assistant(self) -> bool:
        """Return whether the admitted source message should reach the assistant."""

        return self.source_behavior == "continue"


class OhmoAutomationService:
    """Own workflow definitions and background run tasks for one Ohmo gateway.

    Integration: The gateway bridge submits admitted messages and receives an
    immediate source-behavior decision. The service owns definition preflight,
    durable recovery, actions, isolated agents, governed-tool runtime, approval
    delivery, maintenance, and child task cleanup.

    Event loop: Store work is offloaded; every created task is tracked and
    cancelled or awaited by ``stop``. One instance belongs to one gateway loop.

    Change safety: Automation failures must not mutate conversational runtimes,
    bypass channel admission, expand policy capabilities, or blindly replay
    uncertain effects.
    """

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
        tool_api_client: SupportsStreamingMessages | None = None,
        tool_runtime_builder: ToolRuntimeBuilder | None = None,
    ) -> None:
        """Compose one workspace-scoped service without starting async tasks.

        Built-in action names are reserved before trusted plugin actions load so
        plugins cannot silently replace channel, knowledge, or governed-tool
        policy enforcement.
        """

        self.workspace = initialize_workspace(workspace)
        self.cwd = Path(cwd).expanduser().resolve()
        self.bus = bus
        self.provider_profile = provider_profile
        self.actions = actions or ActionRegistry()
        if self.actions.get(ChannelSendAction.name) is None:
            self.actions.register(ChannelSendAction(bus, self.workspace))
        if self.actions.get(KnowledgeUpsertAction.name) is None:
            self.actions.register(KnowledgeUpsertAction(self.workspace))
        existing_tool_action = self.actions.get(GovernedToolAction.name)
        if existing_tool_action is None:
            self._governed_tool_action = GovernedToolAction()
            self.actions.register(self._governed_tool_action)
        elif isinstance(existing_tool_action, GovernedToolAction):
            self._governed_tool_action = existing_tool_action
        else:
            self._governed_tool_action = None
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
        self._tool_api_client = tool_api_client
        self._tool_runtime_builder = tool_runtime_builder or self._build_tool_runtime
        self._tool_runtime: RuntimeBundle | None = None
        self._tool_runtime_names: tuple[str, ...] = ()
        self._tool_runtime_lock = asyncio.Lock()
        self.runner = WorkflowRunner(
            store=self.store,
            actions=self.actions,
            agent_executor=self.agent_executor,
            tool_executor_factory=self._tool_executor_for_run,
        )
        self.definitions: tuple[WorkflowDefinition, ...] = ()
        self.diagnostics: tuple[DefinitionDiagnostic, ...] = ()
        self._tasks: dict[str, asyncio.Task] = {}
        if maintenance_interval_seconds <= 0:
            raise ValueError("maintenance interval must be positive")
        self._maintenance_interval_seconds = maintenance_interval_seconds
        self._maintenance_task: asyncio.Task | None = None
        self._started = False

    async def start(self, *, resume_existing_runs: bool = True) -> None:
        """Validate capabilities, recover state, start maintenance, and optionally resume.

        Targeted local commands disable automatic resumption so operating one run
        cannot race unrelated pending work. Gateway startup uses the default and
        resumes every safe pending or waiting run.
        """

        if self._started:
            return
        await self.validate_configuration(resolve_governed_tools=True)
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
        if resume_existing_runs:
            pending = await asyncio.to_thread(self.store.list_runs, status="pending")
            waiting = await asyncio.to_thread(self.store.list_runs, status="waiting_approval")
            for run in (*pending, *waiting):
                self._schedule(run.id)

    async def validate_configuration(self, *, resolve_governed_tools: bool = False) -> None:
        """Load and capability-check definitions without recovering or executing runs.

        ``resolve_governed_tools`` additionally composes the dedicated tool
        runtime and verifies every declared installed tool. Pure syntax/dry-run
        callers may leave it disabled to avoid opening runtime resources.
        """

        loaded = await asyncio.to_thread(
            load_workflow_definitions,
            get_automations_dir(self.workspace),
        )
        tool_runtime_error = None
        if resolve_governed_tools:
            tool_runtime_error = await self._ensure_tool_runtime(loaded.definitions)
        definitions, preflight = await self._preflight(
            loaded.definitions,
            tool_runtime_error=tool_runtime_error,
        )
        self.definitions = definitions
        self.diagnostics = (*loaded.diagnostics, *preflight)

    async def stop(self) -> None:
        """Cancel maintenance, preserve active runs for recovery, and close resources."""

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
        tool_runtime = self._tool_runtime
        self._tool_runtime = None
        self._tool_runtime_names = ()
        if self._governed_tool_action is not None:
            self._governed_tool_action.bind_registry(None)
        if tool_runtime is not None:
            await close_runtime(tool_runtime)
        self._started = False

    async def _maintenance_loop(self) -> None:
        """Periodically expire approvals and enforce bounded run retention."""

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
        """Sanitize one already-admitted channel message and dispatch its event."""

        return await self.dispatch_event(channel_message_event(message))

    async def dispatch_event(self, event: AutomationEvent) -> AutomationDispatch:
        """Match, reserve, and schedule independent runs without awaiting effects."""

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
        *,
        resume_existing_runs: bool = True,
    ) -> AutomationDispatch:
        """Submit one exact workflow for a local event and schedule only new work."""

        if not self._started:
            await self.start(resume_existing_runs=resume_existing_runs)
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
        """Reset a failed run with explicit uncertain-outcome consent and schedule it."""

        current = await asyncio.to_thread(self.store.load_run, run_id)
        await self._ensure_stored_run_capabilities(current)
        run = await asyncio.to_thread(
            self.store.retry_run,
            run_id,
            allow_unknown_outcome=allow_unknown_outcome,
        )
        self._schedule(run.id)
        return run

    async def cancel_run(self, run_id: str, *, reason: str):
        """Cancel a tracked task first, then checkpoint any remaining active run."""

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
        """Authenticate an actor decision and schedule an approved continuation."""

        current = await asyncio.to_thread(self.store.load_run, run_id)
        if approved:
            await self._ensure_stored_run_capabilities(current)
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
        """Handle admitted approve/reject commands before generic event dispatch."""

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
        """Return definition and live-run counts for the gateway state snapshot."""

        statuses = self.store.status_counts()
        return {
            "loaded": len(self.definitions),
            "invalid": len(self.diagnostics),
            "active": statuses.get("pending", 0) + statuses.get("running", 0),
            "waiting": statuses.get("waiting_approval", 0),
            "failed": statuses.get("failed", 0),
        }

    async def _preflight(
        self,
        definitions: tuple[WorkflowDefinition, ...],
        *,
        tool_runtime_error: str | None = None,
    ) -> tuple[tuple[WorkflowDefinition, ...], tuple[DefinitionDiagnostic, ...]]:
        """Exclude definitions with unavailable actions, skills, agents, or tools."""

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
            if tool_runtime_error and any(
                isinstance(step, ActionStep) and step.action == GovernedToolAction.name
                for step in definition.steps
            ):
                errors.append(tool_runtime_error)
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

    async def _ensure_tool_runtime(
        self,
        definitions: tuple[WorkflowDefinition, ...],
    ) -> str | None:
        """Compose and bind the least-authority runtime needed by tool workflows.

        One runtime exposes the union of declared tool names; each run receives a
        further filtered registry. Setup failures become definition diagnostics
        rather than crashing the gateway.
        """

        async with self._tool_runtime_lock:
            return await self._ensure_tool_runtime_locked(definitions)

    async def _ensure_tool_runtime_locked(
        self,
        definitions: tuple[WorkflowDefinition, ...],
    ) -> str | None:
        """Expand the tool runtime transactionally while holding its setup lock."""

        tool_definitions = tuple(
            definition
            for definition in definitions
            if any(
                isinstance(step, ActionStep) and step.action == GovernedToolAction.name
                for step in definition.steps
            )
        )
        if not tool_definitions:
            return None
        if self._governed_tool_action is None:
            return "the reserved tool.execute action name is owned by another action"
        required_names = set(self._tool_runtime_names)
        required_names.update(
            name
            for definition in tool_definitions
            for name in definition.policy.allowed_tools
        )
        names = tuple(sorted(required_names))
        if self._tool_runtime is not None and names == self._tool_runtime_names:
            return None
        try:
            runtime = await self._tool_runtime_builder(names)
        except Exception as exc:
            logger.exception("ohmo automation governed-tool runtime setup failed")
            return f"cannot initialize governed tools: {type(exc).__name__}: {exc}"
        previous = self._tool_runtime
        self._tool_runtime = runtime
        self._tool_runtime_names = names
        self._governed_tool_action.bind_registry(runtime.tool_registry)
        if previous is not None:
            await close_runtime(previous)
        return None

    async def _ensure_stored_run_capabilities(self, run) -> str | None:
        """Resolve governed tools from an immutable stored definition snapshot."""

        error = await self._ensure_tool_runtime((run.definition,))
        if error:
            logger.warning(
                "ohmo stored automation capability setup failed run_id=%s workflow_id=%s reason=%s",
                run.id,
                run.workflow_id,
                error,
            )
        return error

    async def _build_tool_runtime(self, tool_names: tuple[str, ...]) -> RuntimeBundle:
        """Build a dedicated no-memory, no-session-lifecycle governed-tool runtime."""

        return await build_runtime(
            cwd=str(self.cwd),
            active_profile=self.provider_profile,
            api_client=self._tool_api_client,
            enforce_max_turns=True,
            extra_skill_dirs=(str(get_skills_dir(self.workspace)),),
            extra_plugin_roots=(str(get_plugins_dir(self.workspace)),),
            memory_backend=None,
            include_project_memory=False,
            autodream_context={
                "memory_dir": str(get_memory_dir(self.workspace)),
                "session_dir": str(get_sessions_dir(self.workspace)),
                "app_label": "ohmo personal memory",
                "runner_module": "ohmo",
            },
            tool_allowlist=tool_names,
            post_turn_memory_enabled=False,
            session_lifecycle_enabled=False,
            sandbox_lifecycle_enabled=False,
            coordinator_mode=False,
            include_ambient_context=False,
        )

    def _tool_executor_for_run(self, run) -> GovernedToolExecutor | None:
        """Create a run-scoped executor with exact policy tools and hard denials."""

        runtime = self._tool_runtime
        if runtime is None:
            return None
        settings = runtime.current_settings()
        return GovernedToolExecutor(
            registry=runtime.tool_registry.filtered(run.definition.policy.allowed_tools),
            permission_checker=PermissionChecker(
                automation_permission_settings(settings.permission)
            ),
            cwd=self.cwd,
            hook_executor=runtime.hook_executor,
            metadata={
                **runtime.engine.tool_metadata,
                "automation_run_id": run.id,
                "automation_workflow_id": run.workflow_id,
            },
        )

    def _schedule(self, run_id: str) -> None:
        """Create at most one tracked background task for a durable run."""

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
        """Release task ownership and log unexpected unhandled failures."""

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
        """Execute one run, deliver any approval request, and apply retention."""

        stored = await asyncio.to_thread(self.store.load_run, run_id)
        await self._ensure_stored_run_capabilities(stored)
        run = await self.runner.execute(run_id)
        if run.status == "waiting_approval":
            await self._deliver_approval(run)
            run = await asyncio.to_thread(self.store.load_run, run.id)
        retention = await asyncio.to_thread(self.store.prune)
        for diagnostic in retention.diagnostics:
            logger.warning("ohmo automation retention diagnostic: %s", diagnostic)
        return run

    async def _deliver_approval(self, run) -> None:
        """Publish and durably checkpoint one approval request at most once normally."""

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
                "ancestry": bounded_event_ancestry(
                    *run.event.ancestry,
                    run.event.id,
                    run.id,
                ),
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
    """Combine fan-out behavior with silent, then consume, then continue precedence."""

    behaviors = {definition.source_behavior for definition in definitions}
    if "silent" in behaviors:
        return "silent"
    if "consume" in behaviors:
        return "consume"
    return "continue"
