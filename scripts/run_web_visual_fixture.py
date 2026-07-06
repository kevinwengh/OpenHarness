"""Run a deterministic local OpenHarness host for browser visual auditing.

This fixture intentionally uses the production ``WebUiServer`` and packaged
frontend assets while replacing external state and model execution with bounded
in-memory snapshots. It is launched by Playwright and is not a product entry
point.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from pathlib import Path
from typing import Any

from openharness.ui.backend_host import BackendHostConfig, EventSink, RequestSource
from openharness.ui.protocol import BackendEvent, FrontendRequest, TaskSnapshot, TranscriptItem
from openharness.ui.web_models import (
    WebAppInfo,
    WebAuthInfo,
    WebBootstrap,
    WebNavigationItem,
    WebRuntimeInfo,
    WebWorkspaceInfo,
)
from openharness.ui.web_resources import WebActionResult, WebResourceSnapshot
from openharness.ui.web_server import WebServerConfig, WebUiServer

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "visual-audit-token"


def _bootstrap(_cwd: Path) -> WebBootstrap:
    navigation = [
        ("overview", "Overview", "Local runtime health and product surface", "/", "inspect"),
        ("workbench", "Workbench", "Converse with and supervise the active agent", "/workbench", "operate"),
        ("sessions", "Sessions", "Resume and organize project conversations", "/sessions", "operate"),
        ("runtime", "Runtime", "Provider, model, permission, and sandbox controls", "/runtime", "configure"),
        ("capabilities", "Capabilities", "Tools, skills, plugins, hooks, and MCP", "/capabilities", "inspect"),
        ("work", "Work", "Background tasks, bridges, and schedules", "/work", "operate"),
        ("knowledge", "Knowledge", "Project and session memory", "/knowledge", "inspect"),
        ("autopilot", "Autopilot", "Repository work intake and run health", "/autopilot", "operate"),
    ]
    return WebBootstrap(
        app=WebAppInfo(version="0.1.0-visual-audit"),
        workspace=WebWorkspaceInfo(name="OpenHarness", path="/workspace/OpenHarness"),
        runtime=WebRuntimeInfo(
            profile="local-anthropic",
            provider="anthropic",
            model="local/assistant-model",
            auth=WebAuthInfo(state="configured", label="local token"),
            permission_mode="ask",
            sandbox_enabled=True,
            sandbox_backend="subprocess",
            effort="high",
            max_turns=40,
        ),
        navigation=[
            WebNavigationItem(
                id=item_id,
                label=label,
                description=description,
                path=path,
                depth=depth,
                availability="available",
            )
            for item_id, label, description, path, depth in navigation
        ],
    )


class VisualAuditController:
    """Emit stable runtime events and respond to a few audited interactions."""

    runtime_bundle = None

    def __init__(self, request_source: RequestSource, event_sink: EventSink) -> None:
        self._request_source = request_source
        self._event_sink = event_sink

    async def run(self) -> int:
        await self._event_sink(
            BackendEvent(
                type="ready",
                state={
                    "model": "local/assistant-model",
                    "provider": "anthropic",
                    "permission_mode": "ask",
                    "effort": "high",
                    "max_turns": 40,
                    "sandbox_enabled": True,
                    "sandbox_backend": "subprocess",
                },
                tasks=[
                    TaskSnapshot(
                        id="task-docs",
                        type="background",
                        status="running",
                        description="Review documentation coverage",
                        metadata={"owner": "local runtime"},
                    )
                ],
                commands=["model", "provider", "permissions", "effort", "turns"],
            )
        )
        await self._event_sink(
            BackendEvent(
                type="transcript_item",
                item=TranscriptItem(
                    role="user",
                    text="Audit the browser workspace and summarize the active runtime.",
                ),
            )
        )
        await self._event_sink(
            BackendEvent(
                type="tool_started",
                tool_name="inspect_workspace",
                tool_input={"path": ".", "depth": 2},
                item=TranscriptItem(
                    role="tool",
                    text="",
                    tool_name="inspect_workspace",
                    tool_input={"path": ".", "depth": 2},
                ),
            )
        )
        await self._event_sink(
            BackendEvent(
                type="tool_completed",
                tool_name="inspect_workspace",
                output="Found the runtime, frontend, documentation, and test boundaries.",
                item=TranscriptItem(
                    role="tool_result",
                    text="Found the runtime, frontend, documentation, and test boundaries.",
                    tool_name="inspect_workspace",
                ),
            )
        )
        await self._event_sink(
            BackendEvent(
                type="transcript_item",
                item=TranscriptItem(
                    role="assistant",
                    text=(
                        "### Runtime summary\n\n"
                        "The workspace is connected through the local authenticated host.\n\n"
                        "| Boundary | Status |\n| --- | --- |\n"
                        "| Runtime | Ready |\n| Sandbox | Enabled |\n| Permissions | Ask first |\n\n"
                        "Use the resource areas to inspect bounded operational state."
                    ),
                ),
            )
        )
        await self._event_sink(
            BackendEvent(
                type="todo_update",
                todo_markdown="- [x] Inspect runtime\n- [ ] Review rendered UI\n- [ ] Record evidence",
            )
        )
        await self._event_sink(BackendEvent(type="line_complete"))

        while True:
            request = await self._request_source()
            if request is None or request.type == "shutdown":
                break
            await self._respond(request)
        await self._event_sink(BackendEvent(type="shutdown"))
        return 0

    async def _respond(self, request: FrontendRequest) -> None:
        if request.type == "submit_line":
            line = request.line or "Attached image"
            await self._event_sink(
                BackendEvent(
                    type="transcript_item",
                    item=TranscriptItem(role="user", text=line),
                )
            )
            if "permission" in line.lower():
                await self._event_sink(
                    BackendEvent(
                        type="modal_request",
                        modal={
                            "kind": "permission",
                            "request_id": "permission-visual-audit",
                            "tool_name": "write_file",
                            "reason": "Create the requested local documentation file.",
                        },
                    )
                )
                return
            if "question" in line.lower():
                await self._event_sink(
                    BackendEvent(
                        type="modal_request",
                        modal={
                            "kind": "question",
                            "request_id": "question-visual-audit",
                            "question": "Which audience should this guide prioritize?",
                        },
                    )
                )
                return
            await self._event_sink(BackendEvent(type="assistant_delta", message="I checked the "))
            await self._event_sink(BackendEvent(type="assistant_delta", message="requested area."))
            await self._event_sink(
                BackendEvent(
                    type="assistant_complete",
                    message="I checked the requested area. The deterministic audit path is healthy.",
                )
            )
            await self._event_sink(BackendEvent(type="line_complete"))
            return
        if request.type == "select_command":
            command = request.command or "runtime"
            await self._event_sink(
                BackendEvent(
                    type="select_request",
                    modal={"title": f"Choose {command}", "command": command},
                    select_options=[
                        {
                            "label": "Current setting",
                            "value": "current",
                            "description": "Keep the audited local runtime value.",
                            "active": True,
                        },
                        {
                            "label": "Alternative setting",
                            "value": "alternative",
                            "description": "Preview a second bounded configuration.",
                            "active": False,
                        },
                    ],
                )
            )
            return
        if request.type == "apply_select_command":
            await self._event_sink(
                BackendEvent(
                    type="transcript_item",
                    item=TranscriptItem(
                        role="system",
                        text=f"Updated {request.command} to {request.value} for this audit session.",
                    ),
                )
            )
            await self._event_sink(BackendEvent(type="line_complete"))
            return
        if request.type in {"permission_response", "question_response"}:
            detail = request.answer or request.permission_reply or "dismissed"
            await self._event_sink(
                BackendEvent(
                    type="transcript_item",
                    item=TranscriptItem(role="system", text=f"Decision recorded: {detail}."),
                )
            )
            await self._event_sink(BackendEvent(type="line_complete"))
            return
        if request.type == "interrupt":
            await self._event_sink(BackendEvent(type="line_complete"))


def _controller_factory(
    _config: BackendHostConfig,
    request_source: RequestSource,
    event_sink: EventSink,
) -> VisualAuditController:
    return VisualAuditController(request_source, event_sink)


class VisualAuditResources:
    """Return deterministic, presentation-safe state for every resource area."""

    def snapshot(
        self,
        area: str,
        *,
        runtime_bundle: Any | None = None,
    ) -> WebResourceSnapshot:
        del runtime_bundle
        snapshots: dict[str, dict[str, Any]] = {
            "sessions": {
                "sessions": [
                    {
                        "id": "session-web-audit",
                        "summary": "Browser workspace implementation and rendered review",
                        "message_count": 24,
                        "model": "local/assistant-model",
                        "created_at": "2026-07-05T16:30:00Z",
                    },
                    {
                        "id": "session-provider-notes",
                        "summary": "Local Anthropic-compatible provider configuration",
                        "message_count": 11,
                        "model": "local/assistant-model",
                        "created_at": "2026-07-04T20:15:00Z",
                    },
                ],
                "limits": {"returned": 2, "maximum": 20},
            },
            "capabilities": {
                "tools": [
                    {"name": "read_file", "description": "Read bounded workspace files", "source": "runtime"},
                    {"name": "run_command", "description": "Run approved local commands", "source": "runtime"},
                    {"name": "web_search", "description": "Search when current evidence is required", "source": "runtime"},
                ],
                "commands": [
                    {"name": "/model", "description": "Select the active model", "source": "runtime"},
                    {"name": "/permissions", "description": "Review permission mode", "source": "runtime"},
                ],
                "skills": [
                    {"name": "openharness-development", "description": "Maintain OpenHarness boundaries", "source": "project", "user_invocable": True},
                    {"name": "harness-eval", "description": "Run opt-in real-model evaluations", "source": "project", "user_invocable": True},
                ],
                "plugins": [
                    {"name": "example-local", "description": "Disabled project extension", "enabled": False, "source": "project", "tool_count": 1, "skill_count": 0},
                ],
                "hooks": [{"event": "post_tool", "count": 2}],
                "mcp": [
                    {"name": "documentation", "state": "connected", "transport": "stdio", "detail": "Local documentation index", "tool_count": 3, "resource_count": 8},
                ],
                "providers": [
                    {"name": "local-anthropic", "label": "Local Anthropic", "provider": "anthropic", "model": "local/assistant-model", "configured": True, "auth_state": "configured", "active": True},
                ],
                "trust": {"project_plugins_allowed": False, "blocked_project_plugin_directories": 1},
            },
            "work": {
                "tasks": [
                    {"id": "task-docs", "type": "background", "status": "running", "description": "Review documentation coverage", "created_at": "2026-07-05T16:30:00Z", "progress": 68, "status_note": "Inspecting architecture references"},
                    {"id": "task-tests", "type": "background", "status": "completed", "description": "Run offline test suite", "created_at": "2026-07-05T15:00:00Z", "ended_at": "2026-07-05T15:08:00Z", "progress": 100},
                ],
                "bridges": [
                    {"session_id": "bridge-local", "status": "running", "pid": 4218, "workspace": "OpenHarness", "started_at": "2026-07-05T15:45:00Z"},
                ],
                "cron": [
                    {"name": "documentation-review", "schedule": "0 */8 * * *", "timezone": "America/Los_Angeles", "enabled": True, "next_run": "2026-07-06T00:00:00-07:00", "last_run": "2026-07-05T16:00:00-07:00", "last_status": "completed"},
                    {"name": "weekly-maintenance", "schedule": "0 9 * * 1", "timezone": "America/Los_Angeles", "enabled": False},
                ],
                "cron_history": [
                    {"name": "documentation-review", "status": "completed", "started_at": "2026-07-05T16:00:00-07:00", "ended_at": "2026-07-05T16:02:00-07:00", "returncode": 0},
                ],
                "scheduler_running": True,
            },
            "knowledge": {
                "memories": [
                    {"id": "memory-architecture", "title": "Architecture boundaries", "description": "Reusable runtime and ohmo separation", "preview": "Keep the reusable OpenHarness runtime independent from the ohmo application.", "type": "project", "category": "architecture", "importance": "high", "source": "docs/ARCHITECTURE.md", "tags": ["architecture", "runtime"], "modified_at": "2026-07-05T12:00:00Z", "disabled": False},
                    {"id": "memory-testing", "title": "Validation baseline", "description": "Offline CI and frontend gates", "preview": "Run Python, terminal TypeScript, web component, build, and browser checks.", "type": "project", "category": "testing", "importance": "medium", "source": "docs/TESTING.md", "tags": ["testing", "ci"], "modified_at": "2026-07-05T12:30:00Z", "disabled": False},
                ],
                "limits": {"returned": 2, "maximum": 100},
            },
            "autopilot": {
                "initialized": True,
                "stats": {"queued": 2, "running": 1, "completed": 7, "blocked": 0},
                "cards": [
                    {"id": "idea-web-audit", "title": "Add rendered browser regression gate", "body": "Exercise all primary routes at representative viewports.", "source_kind": "manual_idea", "status": "ready", "score": 92, "labels": ["web", "testing"], "updated_at": "2026-07-05T17:00:00Z"},
                    {"id": "idea-docs", "title": "Enrich operator documentation", "body": "Keep browser workflows and limitations discoverable.", "source_kind": "repository_scan", "status": "queued", "score": 74, "labels": ["documentation"], "updated_at": "2026-07-05T16:45:00Z"},
                ],
                "journal": [
                    {"timestamp": "2026-07-05T17:05:00Z", "kind": "run_completed", "summary": "Web component tests and production build passed", "task_id": "idea-web-audit"},
                ],
            },
        }
        data = snapshots.get(area)
        if data is None:
            raise ValueError(f"Unknown visual audit area: {area}")
        return WebResourceSnapshot(area=area, data=data)

    async def action(self, name: str, payload: object) -> WebActionResult:
        del payload
        allowed = {
            "task.stop",
            "bridge.stop",
            "cron.toggle",
            "cron.run",
            "autopilot.enqueue",
        }
        if name not in allowed:
            raise KeyError(name)
        return WebActionResult(
            action=name,
            message=f"Visual audit action completed: {name}",
            resource={"fixture": True},
        )


async def _run() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stop_event.set)
            installed.append(signum)

    server = WebUiServer(
        WebServerConfig(
            cwd=ROOT,
            host="127.0.0.1",
            port=8765,
            open_browser=False,
            assets_dir=ROOT / "src" / "openharness" / "_web",
            token=TOKEN,
            reconnect_grace_seconds=0,
        ),
        backend_config=BackendHostConfig(cwd=str(ROOT)),
        bootstrap_factory=_bootstrap,
        controller_factory=_controller_factory,
    )
    server._resource_service = VisualAuditResources()
    try:
        async with server:
            print(f"OpenHarness visual fixture: {server.launch_url}", flush=True)
            await stop_event.wait()
    finally:
        for signum in installed:
            with contextlib.suppress(NotImplementedError):
                loop.remove_signal_handler(signum)


if __name__ == "__main__":
    asyncio.run(_run())
