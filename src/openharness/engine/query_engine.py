"""High-level conversation engine.

Integration: This module participates in conversation ownership, provider streaming, tool-result
replay, and usage accounting.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve message/tool pairing, stream ordering, compaction, hooks, permissions,
cancellation, and session persistence.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from openharness.api.client import SupportsStreamingMessages
from openharness.engine.cost_tracker import CostTracker
from openharness.coordinator.coordinator_mode import get_coordinator_user_context
from openharness.engine.messages import ConversationMessage, TextBlock, ToolResultBlock, sanitize_conversation_messages
from openharness.engine.query import AskUserPrompt, PermissionPrompt, QueryContext, remember_user_goal, run_query
from openharness.engine.stream_events import AssistantTurnComplete, StreamEvent
from openharness.config.settings import Settings
from openharness.hooks import HookEvent, HookExecutor
from openharness.permissions.checker import PermissionChecker
from openharness.services.autodream.service import schedule_auto_dream
from openharness.tools.base import ToolRegistry


class QueryEngine:
    """Own conversation state and orchestrate the tool-aware model loop.

    ``build_runtime`` constructs one engine per runtime and UI/channel adapters
    consume its async event streams. The engine is the persistence-facing owner
    of messages, usage, and carryover metadata; ``run_query`` owns individual
    model/tool turns. Preserve that ownership split and do not share one instance
    across event loops without adding explicit synchronization.
    """

    def __init__(
        self,
        *,
        api_client: SupportsStreamingMessages,
        tool_registry: ToolRegistry,
        permission_checker: PermissionChecker,
        cwd: str | Path,
        model: str,
        system_prompt: str,
        max_tokens: int = 4096,
        context_window_tokens: int | None = None,
        auto_compact_threshold_tokens: int | None = None,
        max_turns: int | None = 8,
        permission_prompt: PermissionPrompt | None = None,
        ask_user_prompt: AskUserPrompt | None = None,
        hook_executor: HookExecutor | None = None,
        tool_metadata: dict[str, object] | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Bind runtime services and initialize empty per-session state.

        Callers supply already-resolved clients, tools, policy, hooks, and
        settings. Constructor changes must be reflected in runtime composition,
        restored-session paths, and tests; no asynchronous resource is started
        here because lifecycle startup and cleanup belong to the runtime bundle.
        """
        self._api_client = api_client
        self._tool_registry = tool_registry
        self._permission_checker = permission_checker
        self._cwd = Path(cwd).resolve()
        self._model = model
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens
        self._effort = settings.effort if settings is not None else None
        self._context_window_tokens = context_window_tokens
        self._auto_compact_threshold_tokens = auto_compact_threshold_tokens
        self._max_turns = max_turns
        self._permission_prompt = permission_prompt
        self._ask_user_prompt = ask_user_prompt
        self._hook_executor = hook_executor
        self._tool_metadata = tool_metadata or {}
        self._settings = settings
        self._messages: list[ConversationMessage] = []
        self._cost_tracker = CostTracker()

    @property
    def messages(self) -> list[ConversationMessage]:
        """Return a shallow copy of the provider-visible conversation history.

        Callers may inspect the messages for rendering or persistence but must use
        engine methods to replace state. Message objects themselves are shared, so
        changes to their mutability require a deeper-copy decision here.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return list(self._messages)

    @property
    def max_turns(self) -> int | None:
        """Return the current per-prompt model/tool turn cap, or ``None``.

        UI status and continuation paths read this value; keep its semantics
        aligned with ``QueryContext.max_turns`` and ``MaxTurnsExceeded``.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self._max_turns

    @property
    def api_client(self) -> SupportsStreamingMessages:
        """Expose the active streaming client to runtime and memory services.

        Client replacement must go through ``set_api_client`` so the next query
        uses one coherent provider/model configuration.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self._api_client

    @property
    def model(self) -> str:
        """Return the model identifier used by subsequent provider requests.

        Prompt rendering and optional memory work also inspect this value, so
        model-switching code must update related capability settings together.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self._model

    @property
    def system_prompt(self) -> str:
        """Return the system prompt snapshot used for the next query run.

        ``handle_line`` rebuilds this between user submissions. Avoid mutating it
        during an active async stream, where one ``QueryContext`` already owns a
        consistent prompt value.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self._system_prompt

    @property
    def tool_metadata(self) -> dict[str, object]:
        """Return the shared mutable carryover state for tools and persistence.

        Runtime, compaction, session memory, and session storage intentionally
        observe this same mapping. New keys need bounded values and explicit
        persistence decisions; never place credentials or live resources here.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self._tool_metadata

    @property
    def total_usage(self):
        """Return the accumulated provider usage for the current in-memory session.

        The value is updated from streamed query events and reset by ``clear``.
        Preserve that accounting order when adding event types or retry paths.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self._cost_tracker.total

    def clear(self) -> None:
        """Clear conversation and usage state without rebuilding runtime services.

        Slash-command handling uses this for a fresh chat in the same process.
        Carryover metadata is intentionally not cleared here; changing that
        contract affects session identity, tools, and UI state.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``CostTracker``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._messages.clear()
        self._cost_tracker = CostTracker()

    def set_system_prompt(self, prompt: str) -> None:
        """Replace the system prompt used when constructing future query contexts.

        Existing messages are unaffected. Call this between streamed turns so an
        in-flight ``run_query`` retains a stable prompt.

        Integration: Called by ``OhmoSessionRuntimePool.get_bundle``,
        ``OhmoSessionRuntimePool._stream_command_result``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._system_prompt = prompt

    def set_model(self, model: str) -> None:
        """Select the model identifier for future requests and memory work.

        Runtime model switching is responsible for replacing incompatible clients
        and capability limits alongside this synchronous state update.

        Integration: Called by ``OhmoSessionRuntimePool._stream_command_result``,
        ``create_default_command_registry``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._model = model

    def set_effort(self, effort: str | None) -> None:
        """Set the provider reasoning-effort hint for future query contexts.

        Providers normalize this value differently; keep validation in settings
        and request adapters rather than introducing I/O here.

        Integration: Called by ``create_default_command_registry``,
        ``create_default_command_registry._effort_handler``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._effort = effort

    def set_api_client(self, api_client: SupportsStreamingMessages) -> None:
        """Replace the streaming provider client used by future operations.

        Runtime refresh code owns closing the old client and configuring the new
        one. Do not swap clients while a query stream is active without explicit
        lifecycle coordination.

        Integration: Called by ``refresh_runtime_client``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._api_client = api_client

    def set_max_turns(self, max_turns: int | None) -> None:
        """Set the future per-prompt turn cap, normalizing finite values to one.

        ``None`` deliberately permits an unbounded loop. Preserve this distinction
        for CLI overrides and continuation commands.

        Integration: Called by ``OhmoSessionRuntimePool._stream_command_result``,
        ``create_default_command_registry``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._max_turns = None if max_turns is None else max(1, int(max_turns))

    def set_permission_checker(self, checker: PermissionChecker) -> None:
        """Replace policy evaluation for future tool calls.

        Permission-mode commands use this between turns. The checker captured in
        an existing ``QueryContext`` remains authoritative for its active stream.

        Integration: Called by ``create_default_command_registry``,
        ``create_default_command_registry._permissions_handler``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._permission_checker = checker

    def _build_coordinator_context_message(self) -> ConversationMessage | None:
        """Build the transient coordinator context appended to provider input.

        The message is not part of durable user history; ``run_query`` temporarily
        removes and restores it around assistant messages. Keep the marker text
        aligned with that detection logic and coordinator-state producers.

        Integration: Called by ``QueryEngine.submit_message`` and collaborates with
        ``get_coordinator_user_context``, ``context.get``, ``ConversationMessage``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking; retain lock scope and release behavior.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        context = get_coordinator_user_context()
        worker_tools_context = context.get("workerToolsContext")
        if not worker_tools_context:
            return None
        return ConversationMessage(
            role="user",
            content=[TextBlock(text=f"# Coordinator User Context\n\n{worker_tools_context}")],
        )

    def load_messages(self, messages: list[ConversationMessage]) -> None:
        """Replace conversation state from a validated restore/import source.

        A shallow copy isolates list mutation while retaining message values.
        Callers must sanitize untrusted persisted structures before conversion;
        each submission sanitizes again before provider replay.

        Integration: Called by ``OhmoSessionRuntimePool._save_snapshot``,
        ``_strip_image_blocks_from_engine_history``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._messages = list(messages)

    def _schedule_auto_dream(self) -> None:
        """Schedule best-effort background memory consolidation after a user turn.

        ``schedule_auto_dream`` owns task creation on the running event loop; this
        synchronous wrapper only gathers bounded context. Keep it non-fatal and
        avoid retaining live query objects in the scheduled payload.

        Integration: Called by ``QueryEngine.submit_message`` and collaborates with
        ``_tool_metadata.get``, ``schedule_auto_dream``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if self._settings is None:
            return
        context = self._tool_metadata.get("autodream_context")
        kwargs = dict(context) if isinstance(context, dict) else {}
        schedule_auto_dream(
            cwd=self._cwd,
            settings=self._settings,
            model=self._model,
            current_session_id=str(self._tool_metadata.get("session_id") or ""),
            **kwargs,
        )

    def _prepare_session_memory(self) -> None:
        """Expose the session-memory path to compaction when both gates are enabled.

        This synchronous setup runs immediately before a query. It records path
        metadata but performs no model call; feature-gate or path-schema changes
        must stay aligned with session memory and snapshot restoration.
        """

        if self._settings is None or not self._settings.memory.session_memory_enabled:
            return
        if not self._settings.memory.enabled:
            return
        from openharness.services.session_memory import prepare_session_memory_metadata

        prepare_session_memory_metadata(
            self._cwd,
            self._tool_metadata,
            session_id=str(self._tool_metadata.get("session_id") or "default"),
        )

    async def _update_session_memory(self) -> None:
        """Persist a deterministic session-memory checkpoint after a query attempt.

        ``submit_message`` awaits this from ``finally`` so success, error, and
        cancellation paths converge. The current implementation performs local
        synchronous file work inside the coroutine; keep it bounded or offload it
        before increasing I/O so the event loop is not stalled.
        """

        if self._settings is None or not self._settings.memory.session_memory_enabled:
            return
        if not self._settings.memory.enabled:
            return
        from openharness.services.session_memory import update_session_memory_file

        update_session_memory_file(
            self._cwd,
            list(self._messages),
            tool_metadata=self._tool_metadata,
            session_id=str(self._tool_metadata.get("session_id") or "default"),
        )

    async def _extract_durable_memories(self) -> None:
        """Run optional provider-backed extraction without failing the user turn.

        The pass is awaited after session-memory persistence and may perform a
        model request on the same event loop. Exceptions become diagnostic
        metadata; preserve that best-effort boundary and never append extraction
        traffic to the conversation history.
        """

        if self._settings is None or not self._settings.memory.auto_extract_enabled:
            return
        if not self._settings.memory.enabled:
            return
        from openharness.services.memory_extract import extract_memories_from_turn

        try:
            result = await extract_memories_from_turn(
                cwd=self._cwd,
                api_client=self._api_client,
                model=self._model,
                messages=list(self._messages),
                max_records=self._settings.memory.auto_extract_max_records,
            )
        except Exception as exc:
            self._tool_metadata["memory_extract_last_error"] = str(exc)
            return
        self._tool_metadata["memory_extract_last"] = {
            "skipped": result.skipped,
            "reason": result.reason,
            "written_paths": [str(path) for path in result.written_paths],
        }

    def has_pending_continuation(self) -> bool:
        """Detect tool results that still require a follow-up provider turn.

        Continuation commands rely on assistant tool-use/user tool-result pairing,
        including after sanitization and resume. Keep this predicate consistent
        with provider replay rules rather than treating any final user message as
        pending work.

        Integration: Called by ``create_default_command_registry``,
        ``create_default_command_registry._continue_handler`` and collaborates with
        ``reversed``, ``any``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if not self._messages:
            return False
        last = self._messages[-1]
        if last.role != "user":
            return False
        if not any(isinstance(block, ToolResultBlock) for block in last.content):
            return False
        for msg in reversed(self._messages[:-1]):
            if msg.role != "assistant":
                continue
            return bool(msg.tool_uses)
        return False

    async def submit_message(self, prompt: str | ConversationMessage) -> AsyncIterator[StreamEvent]:
        """Append one user message and stream its complete model/tool lifecycle.

        This is the primary UI/channel entrypoint: it records goal state, prepares
        memory, sanitizes history, fires the submit hook, builds an immutable
        ``QueryContext``, and forwards ``run_query`` events while updating message
        and usage ownership. The ``finally`` block must remain cancellation-safe
        so session memory, optional extraction, and autodream scheduling run after
        every attempt. Do not introduce blocking work into this async generator.
        """
        user_message = (
            prompt
            if isinstance(prompt, ConversationMessage)
            else ConversationMessage.from_user_text(prompt)
        )
        if user_message.text.strip() and not self._tool_metadata.pop("_suppress_next_user_goal", False):
            remember_user_goal(self._tool_metadata, user_message.text)
        self._prepare_session_memory()
        self._messages = sanitize_conversation_messages(self._messages)
        self._messages.append(user_message)
        if self._hook_executor is not None:
            await self._hook_executor.execute(
                HookEvent.USER_PROMPT_SUBMIT,
                {
                    "event": HookEvent.USER_PROMPT_SUBMIT.value,
                    "prompt": user_message.text,
                },
            )
        context = QueryContext(
            api_client=self._api_client,
            tool_registry=self._tool_registry,
            permission_checker=self._permission_checker,
            cwd=self._cwd,
            model=self._model,
            system_prompt=self._system_prompt,
            max_tokens=self._max_tokens,
            effort=self._effort,
            context_window_tokens=self._context_window_tokens,
            auto_compact_threshold_tokens=self._auto_compact_threshold_tokens,
            max_turns=self._max_turns,
            permission_prompt=self._permission_prompt,
            ask_user_prompt=self._ask_user_prompt,
            hook_executor=self._hook_executor,
            tool_metadata=self._tool_metadata,
        )
        query_messages = list(self._messages)
        coordinator_context = self._build_coordinator_context_message()
        if coordinator_context is not None:
            query_messages.append(coordinator_context)
        try:
            async for event, usage in run_query(context, query_messages):
                if isinstance(event, AssistantTurnComplete):
                    self._messages = list(query_messages)
                if usage is not None:
                    self._cost_tracker.add(usage)
                yield event
        finally:
            await self._update_session_memory()
            await self._extract_durable_memories()
            self._schedule_auto_dream()

    async def continue_pending(self, *, max_turns: int | None = None) -> AsyncIterator[StreamEvent]:
        """Resume pending tool-result replay without appending a new user message.

        Command handlers call this only after ``has_pending_continuation``. It
        rebuilds a query context from current runtime services, streams on the
        caller's event loop, and then refreshes memory. Preserve the absence of a
        submit hook/new goal and keep optional turn overrides local to this run.
        """
        self._prepare_session_memory()
        self._messages = sanitize_conversation_messages(self._messages)
        context = QueryContext(
            api_client=self._api_client,
            tool_registry=self._tool_registry,
            permission_checker=self._permission_checker,
            cwd=self._cwd,
            model=self._model,
            system_prompt=self._system_prompt,
            max_tokens=self._max_tokens,
            effort=self._effort,
            context_window_tokens=self._context_window_tokens,
            auto_compact_threshold_tokens=self._auto_compact_threshold_tokens,
            max_turns=max_turns if max_turns is not None else self._max_turns,
            permission_prompt=self._permission_prompt,
            ask_user_prompt=self._ask_user_prompt,
            hook_executor=self._hook_executor,
            tool_metadata=self._tool_metadata,
        )
        async for event, usage in run_query(context, self._messages):
            if usage is not None:
                self._cost_tracker.add(usage)
            yield event
        await self._update_session_memory()
        await self._extract_durable_memories()
