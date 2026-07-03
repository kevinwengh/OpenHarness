"""Default Textual terminal UI for OpenHarness.

Integration: This module participates in runtime composition and adapters for CLI, React,
Textual, headless, and ohmo callers.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve startup/readiness, protocol ordering, callback ownership, interruption,
persistence, and resource cleanup.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from rich.panel import Panel
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from openharness.api.client import SupportsStreamingMessages
from openharness.config.settings import load_settings, save_settings
from openharness.coordinator.coordinator_mode import is_coordinator_mode
from openharness.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CompactProgressEvent,
    ErrorEvent,
    StatusEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from openharness.tasks import get_task_manager
from openharness.ui.coordinator_drain import drain_coordinator_async_agents
from openharness.ui.runtime import build_runtime, close_runtime, handle_line, start_runtime


@dataclass(frozen=True)
class AppConfig:
    """Configuration for a terminal app session.

    Integration: Constructed or referenced by ``OpenHarnessTerminalApp.__init__``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    prompt: str | None = None
    model: str | None = None
    base_url: str | None = None
    system_prompt: str | None = None
    api_key: str | None = None
    api_client: SupportsStreamingMessages | None = None


class PermissionScreen(ModalScreen[bool]):
    """Simple approval modal for mutating tools.

    Integration: Constructed or referenced by ``OpenHarnessTerminalApp._ask_permission``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    BINDINGS = [
        Binding("escape", "deny", "Deny"),
        Binding("y", "allow", "Allow"),
        Binding("n", "deny", "Deny"),
    ]

    def __init__(self, tool_name: str, reason: str) -> None:
        """Initialize ``PermissionScreen`` and bind its runtime dependencies.

        Integration: Exposed through ``PermissionScreen``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        super().__init__()
        self._tool_name = tool_name
        self._reason = reason

    def compose(self) -> ComposeResult:
        """Compose the child widgets exposed by this Textual component.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``Container``, ``Static``, ``Horizontal``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve yield ordering and partial-consumption behavior expected by
        callers.
        """
        yield Container(
            Static(
                Panel.fit(
                    f"Allow tool [bold]{self._tool_name}[/bold]?\n\n{self._reason}",
                    title="Permission Required",
                )
            ),
            Horizontal(
                Button("Allow", id="allow", variant="success"),
                Button("Deny", id="deny", variant="error"),
                classes="permission-actions",
            ),
            id="permission-dialog",
        )

    @on(Button.Pressed)
    def handle_button_press(self, event: Button.Pressed) -> None:
        """Handle button press for the enclosing subsystem.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``on``, ``dismiss``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.dismiss(event.button.id == "allow")

    def action_allow(self) -> None:
        """Handle the allow Textual action.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``dismiss``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.dismiss(True)

    def action_deny(self) -> None:
        """Handle the deny Textual action.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``dismiss``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.dismiss(False)


class QuestionScreen(ModalScreen[str]):
    """Prompt the user for a short answer during tool execution.

    Integration: Constructed or referenced by ``OpenHarnessTerminalApp._ask_question``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "submit", "Submit"),
    ]

    def __init__(self, question: str) -> None:
        """Initialize ``QuestionScreen`` and bind its runtime dependencies.

        Integration: Exposed through ``QuestionScreen``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        """Compose the child widgets exposed by this Textual component.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``Container``, ``Static``, ``Input``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve yield ordering and partial-consumption behavior expected by
        callers.
        """
        yield Container(
            Static(
                Panel.fit(
                    self._question,
                    title="Question",
                )
            ),
            Input(placeholder="Type your answer", id="question-input"),
            Horizontal(
                Button("Submit", id="submit", variant="primary"),
                Button("Cancel", id="cancel", variant="default"),
                classes="permission-actions",
            ),
            id="permission-dialog",
        )

    def on_mount(self) -> None:
        """Handle the mount lifecycle event.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``focus``, ``query_one``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.query_one("#question-input", Input).focus()

    @on(Button.Pressed)
    def handle_button_press(self, event: Button.Pressed) -> None:
        """Handle button press for the enclosing subsystem.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``on``, ``dismiss``, ``value.strip``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if event.button.id == "submit":
            self.dismiss(self.query_one("#question-input", Input).value.strip())
            return
        self.dismiss("")

    @on(Input.Submitted, "#question-input")
    def handle_submit(self, event: Input.Submitted) -> None:
        """Handle submit for the enclosing subsystem.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``on``, ``dismiss``, ``event.value.strip``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.dismiss(event.value.strip())

    def action_submit(self) -> None:
        """Handle the submit Textual action.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``dismiss``, ``value.strip``, ``query_one``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.dismiss(self.query_one("#question-input", Input).value.strip())

    def action_cancel(self) -> None:
        """Handle the cancel Textual action.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``dismiss``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.dismiss("")


class OpenHarnessTerminalApp(App[None]):
    """Terminal-first Textual UI.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Event loop: Async methods ``on_mount``, ``on_unmount``, ``_ask_permission``,
    ``_ask_question`` run on their caller's loop; instances must retain clear task,
    cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    CSS = """
    Screen {
        layout: vertical;
    }

    #main-row {
        height: 1fr;
    }

    #transcript-column {
        width: 3fr;
        min-width: 60;
    }

    #side-column {
        width: 1fr;
        min-width: 28;
    }

    #transcript {
        height: 1fr;
        border: solid $accent;
    }

    #current-response {
        min-height: 3;
        max-height: 8;
        border: round $primary;
        padding: 0 1;
    }

    #composer {
        dock: bottom;
        height: 3;
        border: solid $accent;
    }

    #status-bar, #tasks-panel, #mcp-panel {
        border: round $surface;
        padding: 0 1;
        margin-bottom: 1;
    }

    #permission-dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        background: $panel;
        border: round $accent;
    }

    .permission-actions {
        align: center middle;
        height: auto;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+l", "clear_conversation", "Clear"),
        Binding("ctrl+r", "refresh_sidebars", "Refresh"),
        Binding("ctrl+k", "toggle_vim", "Vim"),
        Binding("ctrl+v", "toggle_voice", "Voice"),
        Binding("ctrl+d", "quit_session", "Exit"),
    ]

    def __init__(
        self,
        *,
        prompt: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        system_prompt: str | None = None,
        api_key: str | None = None,
        api_client: SupportsStreamingMessages | None = None,
    ) -> None:
        """Initialize ``OpenHarnessTerminalApp`` and bind its runtime dependencies.

        Integration: Exposed through ``OpenHarnessTerminalApp`` and collaborates with
        ``AppConfig``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        super().__init__()
        self._config = AppConfig(
            prompt=prompt,
            model=model,
            base_url=base_url,
            system_prompt=system_prompt,
            api_key=api_key,
            api_client=api_client,
        )
        self._bundle = None
        self._assistant_buffer = ""
        self._busy = False
        self.transcript_lines: list[str] = []
        self._last_status_snapshot: tuple[object, ...] | None = None
        self._last_tasks_snapshot: tuple[tuple[str, str, object, object], ...] | None = None
        self._last_mcp_summary: str | None = None
        self._last_current_response: str | None = None

    def compose(self) -> ComposeResult:
        """Compose the child widgets exposed by this Textual component.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``Header``, ``Horizontal``, ``Footer``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve yield ordering and partial-consumption behavior expected by
        callers.
        """
        yield Header(show_clock=True)
        with Horizontal(id="main-row"):
            with Vertical(id="transcript-column"):
                yield RichLog(id="transcript", wrap=True, highlight=True, markup=True)
                yield Static("Ready.", id="current-response")
                yield Input(placeholder="Ask OpenHarness or enter a /command", id="composer")
            with Vertical(id="side-column"):
                yield Static("Starting...", id="status-bar")
                yield Static("No tasks yet.", id="tasks-panel")
                yield Static("No MCP servers configured.", id="mcp-panel")
        yield Footer()

    async def on_mount(self) -> None:
        """Handle the mount lifecycle event.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``focus``, ``_refresh_sidebars``, ``build_runtime``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._bundle = await build_runtime(
            prompt=self._config.prompt,
            cwd=str(self.app.cwd) if getattr(self.app, 'cwd', None) else None,
            model=self._config.model,
            base_url=self._config.base_url,
            system_prompt=self._config.system_prompt,
            api_key=self._config.api_key,
            api_client=self._config.api_client,
            permission_prompt=self._ask_permission,
            ask_user_prompt=self._ask_question,
        )
        await start_runtime(self._bundle)
        self.query_one("#composer", Input).focus()
        self._refresh_sidebars(force=True)
        if self._config.prompt:
            self.call_later(lambda: asyncio.create_task(self._process_line(self._config.prompt or "")))

    async def on_unmount(self) -> None:
        """Handle the unmount lifecycle event.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``close_runtime``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if self._bundle is not None:
            await close_runtime(self._bundle)

    async def _ask_permission(self, tool_name: str, reason: str) -> bool:
        """Ask for permission for the enclosing subsystem.

        Integration: Used as an internal helper or callback at this module boundary and
        collaborates with ``_open_modal``, ``PermissionScreen``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return bool(await self._open_modal(PermissionScreen(tool_name, reason)))

    async def _ask_question(self, question: str) -> str:
        """Ask for question for the enclosing subsystem.

        Integration: Used as an internal helper or callback at this module boundary and
        collaborates with ``_open_modal``, ``QuestionScreen``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return str(await self._open_modal(QuestionScreen(question)) or "")

    async def _open_modal(self, screen: ModalScreen) -> object:
        """Open modal for the enclosing subsystem.

        Integration: Called by ``OpenHarnessTerminalApp._ask_permission``,
        ``OpenHarnessTerminalApp._ask_question`` and collaborates with
        ``asyncio.get_running_loop``, ``loop.create_future``, ``push_screen``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[object] = loop.create_future()

        def _done(result: object) -> None:
            """Resolve the pending UI interaction with its selected result.

            Integration: Used as an internal helper or callback at this module boundary and
            collaborates with ``future.done``, ``future.set_result``.

            Concurrency: This is synchronous; preserve deterministic behavior for its direct
            callers.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            if not future.done():
                future.set_result(result)

        self.push_screen(screen, callback=_done)
        return await future

    @on(Input.Submitted, "#composer")
    async def handle_submit(self, event: Input.Submitted) -> None:
        """Handle submit for the enclosing subsystem.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``on``, ``_process_line``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        event.input.value = ""
        await self._process_line(event.value)

    async def _process_line(self, line: str) -> None:
        """Process line for the enclosing subsystem.

        Integration: Exposed through ``OpenHarnessTerminalApp`` and collaborates with
        ``query_one``, ``_append_line``, ``_set_current_response``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if not line.strip() or self._bundle is None or self._busy:
            return
        self._busy = True
        composer = self.query_one("#composer", Input)
        composer.disabled = True
        self._append_line(f"user> {line}")
        self._set_current_response("[dim]Working...[/dim]")
        try:
            should_continue = await handle_line(
                self._bundle,
                line,
                print_system=self._print_system,
                render_event=self._render_event,
                clear_output=self._clear_transcript,
            )
            if is_coordinator_mode():
                await drain_coordinator_async_agents(
                    self._bundle,
                    prompt_seed=line,
                    print_system=self._print_system,
                    render_event=self._render_event,
                )
            self._refresh_sidebars()
            if not should_continue:
                self.exit()
        finally:
            self._busy = False
            composer.disabled = False
            composer.focus()

    async def _print_system(self, message: str) -> None:
        """Render one system message through the active output adapter.

        Integration: Used as an internal helper or callback at this module boundary and
        collaborates with ``_append_line``, ``_set_current_response``.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._append_line(f"system> {message}")
        self._set_current_response("Ready.")

    async def _render_event(self, event: StreamEvent) -> None:
        """Render event for the enclosing subsystem.

        Integration: Used as an internal helper or callback at this module boundary and
        collaborates with ``_set_current_response``, ``_append_line``, ``json.dumps``.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if isinstance(event, AssistantTextDelta):
            self._assistant_buffer += event.text
            self._set_current_response(f"[bold]assistant>[/bold] {self._assistant_buffer}")
            return

        if isinstance(event, CompactProgressEvent):
            if event.phase == "hooks_start":
                if event.trigger == "reactive":
                    self._set_current_response("[dim]Preparing retry compaction...[/dim]")
                else:
                    self._set_current_response("[dim]Preparing conversation compaction...[/dim]")
            elif event.phase == "compact_start":
                if event.trigger == "reactive":
                    self._set_current_response("[dim]Context too large. Compacting and retrying...[/dim]")
                else:
                    self._set_current_response("[dim]Compacting conversation memory...[/dim]")
            elif event.phase == "compact_retry":
                attempt = f" (attempt {event.attempt})" if event.attempt is not None else ""
                self._set_current_response(f"[dim]Retrying compaction{attempt}...[/dim]")
            elif event.phase == "compact_failed":
                self._append_line(f"system> Compaction failed: {event.message or 'unknown error'}")
                self._set_current_response("Ready.")
            elif event.phase == "compact_end":
                self._set_current_response("[dim]Compaction complete.[/dim]")
            elif event.phase == "session_memory_start":
                self._set_current_response("[dim]Condensing earlier conversation...[/dim]")
            elif event.phase == "session_memory_end":
                self._set_current_response("[dim]Condensed earlier conversation.[/dim]")
            elif event.phase == "context_collapse_start":
                self._set_current_response("[dim]Collapsing oversized context...[/dim]")
            elif event.phase == "context_collapse_end":
                self._set_current_response("[dim]Context collapse complete.[/dim]")
            return

        if isinstance(event, AssistantTurnComplete):
            text = self._assistant_buffer or event.message.text or "(empty response)"
            self._append_line(f"assistant> {text}")
            self._assistant_buffer = ""
            self._set_current_response("Ready.")
            return

        if isinstance(event, ToolExecutionStarted):
            payload = json.dumps(event.tool_input, ensure_ascii=False)
            self._append_line(f"tool> {event.tool_name} {payload}")
            return

        if isinstance(event, ToolExecutionCompleted):
            prefix = "tool-error>" if event.is_error else "tool-result>"
            self._append_line(f"{prefix} {event.tool_name}: {event.output}")
            return

        if isinstance(event, ErrorEvent):
            self._append_line(f"error> {event.message}")
            self._assistant_buffer = ""
            self._set_current_response("Ready.")
            return
        if isinstance(event, StatusEvent):
            self._append_line(f"system> {event.message}")

    def action_clear_conversation(self) -> None:
        """Handle the clear conversation Textual action.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_bundle.engine.clear``, ``clear``, ``transcript_lines.clear``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if self._bundle is None:
            return
        self._bundle.engine.clear()
        self.query_one("#transcript", RichLog).clear()
        self.transcript_lines.clear()
        self._set_current_response("Conversation cleared.")
        self._refresh_sidebars()

    def action_refresh_sidebars(self) -> None:
        """Handle the refresh sidebars Textual action.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_refresh_sidebars``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._refresh_sidebars(force=True)

    def action_toggle_vim(self) -> None:
        """Handle the toggle vim Textual action.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``load_settings``, ``save_settings``, ``_refresh_sidebars``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if self._bundle is None:
            return
        current = self._bundle.app_state.get().vim_enabled
        settings = load_settings()
        settings.vim_mode = not current
        save_settings(settings)
        self._bundle.app_state.set(vim_enabled=not current)
        self._refresh_sidebars()

    def action_toggle_voice(self) -> None:
        """Handle the toggle voice Textual action.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``load_settings``, ``save_settings``, ``_refresh_sidebars``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if self._bundle is None:
            return
        current = self._bundle.app_state.get().voice_enabled
        settings = load_settings()
        settings.voice_mode = not current
        save_settings(settings)
        self._bundle.app_state.set(voice_enabled=not current)
        self._refresh_sidebars()

    def action_quit_session(self) -> None:
        """Handle the quit session Textual action.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``exit``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.exit()

    def _append_line(self, message: str) -> None:
        """Append line for the enclosing subsystem.

        Integration: Called by ``OpenHarnessTerminalApp._process_line``,
        ``OpenHarnessTerminalApp._print_system`` and collaborates with
        ``transcript_lines.append``, ``write``, ``query_one``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.transcript_lines.append(message)
        self.query_one("#transcript", RichLog).write(message)

    async def _clear_transcript(self) -> None:
        """Clear transcript for the enclosing subsystem.

        Integration: Used as an internal helper or callback at this module boundary and
        collaborates with ``clear``, ``transcript_lines.clear``, ``query_one``.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.query_one("#transcript", RichLog).clear()
        self.transcript_lines.clear()

    def _set_current_response(self, message: str) -> None:
        """Set current response for the enclosing subsystem.

        Integration: Called by ``OpenHarnessTerminalApp._process_line``,
        ``OpenHarnessTerminalApp._print_system`` and collaborates with ``update``,
        ``query_one``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if message == self._last_current_response:
            return
        self.query_one("#current-response", Static).update(message)
        self._last_current_response = message

    def _refresh_sidebars(self, *, force: bool = False) -> None:
        """Refresh sidebars for the enclosing subsystem.

        Integration: Called by ``OpenHarnessTerminalApp.on_mount``,
        ``OpenHarnessTerminalApp._process_line`` and collaborates with
        ``_bundle.app_state.get``, ``list_tasks``, ``_bundle.mcp_summary``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if self._bundle is None:
            return
        state = self._bundle.app_state.get()
        usage = self._bundle.engine.total_usage
        status_snapshot = (
            state.model,
            state.permission_mode,
            state.fast_mode,
            state.output_style,
            state.vim_enabled,
            state.voice_enabled,
            usage.total_tokens,
            len(self._bundle.engine.messages),
        )
        if force or status_snapshot != self._last_status_snapshot:
            status_lines = [
                "[b]Status[/b]",
                f"model: {state.model}",
                f"permissions: {state.permission_mode}",
                f"fast: {'on' if state.fast_mode else 'off'}",
                f"style: {state.output_style}",
                f"vim: {'on' if state.vim_enabled else 'off'}",
                f"voice: {'on' if state.voice_enabled else 'off'}",
                f"tokens: {usage.total_tokens}",
                f"messages: {len(self._bundle.engine.messages)}",
            ]
            self.query_one("#status-bar", Static).update("\n".join(status_lines))
            self._last_status_snapshot = status_snapshot

        tasks = get_task_manager().list_tasks()
        tasks_snapshot = tuple(
            (
                task.id,
                task.status,
                task.metadata.get("progress"),
                task.metadata.get("status_note"),
            )
            for task in tasks[:10]
        )
        if force or tasks_snapshot != self._last_tasks_snapshot:
            if tasks:
                task_lines = ["[b]Tasks[/b]"]
                for task in tasks[:10]:
                    suffix: list[str] = []
                    if task.metadata.get("progress"):
                        suffix.append(f"{task.metadata['progress']}%")
                    if task.metadata.get("status_note"):
                        suffix.append(task.metadata["status_note"])
                    detail = f" ({' | '.join(suffix)})" if suffix else ""
                    task_lines.append(f"{task.id} {task.status} {task.description}{detail}")
            else:
                task_lines = ["[b]Tasks[/b]", "No background tasks."]
            self.query_one("#tasks-panel", Static).update("\n".join(task_lines))
            self._last_tasks_snapshot = tasks_snapshot

        mcp_summary = self._bundle.mcp_summary()
        if force or mcp_summary != self._last_mcp_summary:
            self.query_one("#mcp-panel", Static).update(mcp_summary)
            self._last_mcp_summary = mcp_summary
