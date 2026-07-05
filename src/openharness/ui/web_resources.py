"""Bounded resource snapshots and allowlisted actions for the local web UI."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from openharness.auth.manager import AuthManager
from openharness.autopilot import RepoAutopilotStore
from openharness.bridge import get_bridge_manager
from openharness.commands import create_default_command_registry
from openharness.config import load_settings
from openharness.config.paths import get_project_autopilot_registry_path
from openharness.hooks import HookEvent, load_hook_registry
from openharness.memory.scan import scan_memory_files
from openharness.plugins import load_plugins
from openharness.plugins.loader import get_project_plugins_dir
from openharness.services.cron import get_cron_job, load_cron_jobs, set_job_enabled
from openharness.services.cron_scheduler import execute_job, is_scheduler_running, load_history
from openharness.skills.loader import load_skill_registry
from openharness.tasks import get_task_manager
from openharness.tools import create_default_tool_registry


WebResourceArea = Literal["capabilities", "work", "knowledge", "autopilot"]


class WebResourceSnapshot(BaseModel):
    """Versioned response envelope shared by the four operational areas."""

    schema_version: Literal[1] = 1
    area: WebResourceArea
    data: dict[str, Any]


class WebActionResult(BaseModel):
    """Bounded success payload returned by one explicit web action."""

    schema_version: Literal[1] = 1
    action: str
    message: str
    resource: dict[str, Any] | None = None


class _ActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskStopBody(_ActionBody):
    task_id: str = Field(min_length=1, max_length=128)


class BridgeStopBody(_ActionBody):
    session_id: str = Field(min_length=1, max_length=128)


class CronToggleBody(_ActionBody):
    name: str = Field(min_length=1, max_length=128)
    enabled: bool


class CronRunBody(_ActionBody):
    name: str = Field(min_length=1, max_length=128)


class AutopilotEnqueueBody(_ActionBody):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=20_000)


_ACTION_MODELS: dict[str, type[_ActionBody]] = {
    "task.stop": TaskStopBody,
    "bridge.stop": BridgeStopBody,
    "cron.toggle": CronToggleBody,
    "cron.run": CronRunBody,
    "autopilot.enqueue": AutopilotEnqueueBody,
}


def _short(value: object, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _plugin_source(path: Path, cwd: Path) -> str:
    try:
        path.resolve().relative_to(cwd)
        return "project"
    except ValueError:
        return "user"


class WebResourceService:
    """Adapt existing subsystem owners into bounded browser presentation data."""

    def __init__(self, cwd: str | Path) -> None:
        self.cwd = Path(cwd).expanduser().resolve()

    def snapshot(self, area: WebResourceArea, *, runtime_bundle: Any | None = None) -> WebResourceSnapshot:
        if area == "capabilities":
            data = self._capabilities(runtime_bundle)
        elif area == "work":
            data = self._work()
        elif area == "knowledge":
            data = self._knowledge()
        elif area == "autopilot":
            data = self._autopilot()
        else:  # pragma: no cover - Literal and router constrain this
            raise ValueError(f"Unknown web resource area: {area}")
        return WebResourceSnapshot(area=area, data=data)

    async def action(self, name: str, payload: object) -> WebActionResult:
        model = _ACTION_MODELS.get(name)
        if model is None:
            raise KeyError(name)
        body = model.model_validate(payload)
        if isinstance(body, TaskStopBody):
            task = await get_task_manager().stop_task(body.task_id)
            return WebActionResult(
                action=name,
                message=f"Stopped task {task.id}",
                resource={"id": task.id, "status": task.status},
            )
        if isinstance(body, BridgeStopBody):
            await get_bridge_manager().stop(body.session_id)
            return WebActionResult(
                action=name,
                message=f"Stopped bridge session {body.session_id}",
                resource={"session_id": body.session_id, "status": "stopped"},
            )
        if isinstance(body, CronToggleBody):
            updated = await asyncio.to_thread(set_job_enabled, body.name, body.enabled)
            if not updated:
                raise ValueError(f"Unknown cron job: {body.name}")
            state = "enabled" if body.enabled else "disabled"
            return WebActionResult(
                action=name,
                message=f"Cron job {body.name} {state}",
                resource={"name": body.name, "enabled": body.enabled},
            )
        if isinstance(body, CronRunBody):
            job = await asyncio.to_thread(get_cron_job, body.name)
            if job is None:
                raise ValueError(f"Unknown cron job: {body.name}")
            entry = await execute_job(job)
            return WebActionResult(
                action=name,
                message=f"Cron job {body.name} finished with status {entry.get('status', 'unknown')}",
                resource={
                    "name": body.name,
                    "status": str(entry.get("status", "unknown")),
                    "returncode": entry.get("returncode"),
                },
            )
        assert isinstance(body, AutopilotEnqueueBody)
        card, created = await asyncio.to_thread(
            RepoAutopilotStore(self.cwd).enqueue_card,
            source_kind="manual_idea",
            title=body.title,
            body=body.body,
        )
        return WebActionResult(
            action=name,
            message=("Added" if created else "Updated") + f" autopilot card {card.id}",
            resource={"id": card.id, "title": card.title, "status": card.status},
        )

    def _capabilities(self, runtime_bundle: Any | None) -> dict[str, Any]:
        settings = load_settings()
        if runtime_bundle is not None:
            tools = runtime_bundle.tool_registry.list_tools()
            commands = runtime_bundle.commands.list_commands()
            plugins = runtime_bundle.current_plugins()
            mcp_statuses = runtime_bundle.mcp_manager.list_statuses()
            extra_skill_dirs = runtime_bundle.extra_skill_dirs
            extra_plugin_roots = runtime_bundle.extra_plugin_roots
        else:
            tools = create_default_tool_registry().list_tools()
            commands = create_default_command_registry().list_commands()
            plugins = load_plugins(settings, self.cwd)
            mcp_statuses = []
            extra_skill_dirs = ()
            extra_plugin_roots = ()

        skills = load_skill_registry(
            self.cwd,
            settings=settings,
            extra_skill_dirs=extra_skill_dirs,
            extra_plugin_roots=extra_plugin_roots,
        ).list_skills()
        hooks = load_hook_registry(settings, plugins)
        auth_profiles = AuthManager(settings).get_profile_statuses()
        project_plugins_dir = get_project_plugins_dir(self.cwd)
        blocked_project_plugins = (
            sum(1 for child in project_plugins_dir.iterdir() if child.is_dir())
            if project_plugins_dir.exists() and not settings.allow_project_plugins
            else 0
        )
        live_mcp = {
            status.name: {
                "name": status.name,
                "state": status.state,
                "transport": status.transport,
                "detail": _short(status.detail, 240),
                "tool_count": len(status.tools),
                "resource_count": len(status.resources),
            }
            for status in mcp_statuses
        }
        for name, config in settings.mcp_servers.items():
            live_mcp.setdefault(
                name,
                {
                    "name": name,
                    "state": "configured",
                    "transport": getattr(config, "type", "unknown"),
                    "detail": "Not connected in the active runtime",
                    "tool_count": 0,
                    "resource_count": 0,
                },
            )
        return {
            "tools": [
                {"name": tool.name, "description": _short(tool.description), "source": "runtime"}
                for tool in sorted(tools, key=lambda item: item.name)[:200]
            ],
            "commands": [
                {"name": f"/{command.name}", "description": _short(command.description), "source": "runtime"}
                for command in sorted(commands, key=lambda item: item.name)[:200]
            ],
            "skills": [
                {
                    "name": skill.command_name or skill.name,
                    "description": _short(skill.description),
                    "source": skill.source,
                    "user_invocable": skill.user_invocable,
                }
                for skill in skills[:200]
            ],
            "plugins": [
                {
                    "name": plugin.manifest.name,
                    "description": _short(plugin.manifest.description),
                    "enabled": plugin.enabled,
                    "source": _plugin_source(plugin.path, self.cwd),
                    "tool_count": len(plugin.tools),
                    "skill_count": len(plugin.skills),
                }
                for plugin in plugins[:100]
            ],
            "hooks": [
                {"event": event.value, "count": len(hooks.get(event))}
                for event in HookEvent
                if hooks.get(event)
            ],
            "mcp": list(live_mcp.values())[:100],
            "providers": [
                {
                    "name": name,
                    "label": _short(status.get("label"), 100),
                    "provider": status.get("provider"),
                    "model": status.get("model"),
                    "configured": bool(status.get("configured")),
                    "active": bool(status.get("active")),
                }
                for name, status in list(auth_profiles.items())[:100]
            ],
            "trust": {
                "project_plugins_allowed": settings.allow_project_plugins,
                "blocked_project_plugin_directories": blocked_project_plugins,
            },
        }

    def _work(self) -> dict[str, Any]:
        tasks = get_task_manager().list_tasks()[:100]
        bridges = get_bridge_manager().list_sessions()[:100]
        jobs = load_cron_jobs()[:100]
        return {
            "tasks": [
                {
                    "id": task.id,
                    "type": task.type,
                    "status": task.status,
                    "description": _short(task.description),
                    "created_at": task.created_at,
                    "started_at": task.started_at,
                    "ended_at": task.ended_at,
                    "progress": task.metadata.get("progress"),
                    "status_note": _short(task.metadata.get("status_note"), 200),
                }
                for task in tasks
            ],
            "bridges": [
                {
                    "session_id": item.session_id,
                    "status": item.status,
                    "pid": item.pid,
                    "workspace": Path(item.cwd).name,
                    "started_at": item.started_at,
                }
                for item in bridges
            ],
            "cron": [
                {
                    "name": str(job.get("name", "")),
                    "schedule": str(job.get("schedule", "")),
                    "timezone": str(job.get("timezone") or job.get("tz") or "UTC"),
                    "enabled": bool(job.get("enabled", True)),
                    "next_run": job.get("next_run"),
                    "last_run": job.get("last_run"),
                    "last_status": job.get("last_status"),
                }
                for job in jobs
            ],
            "cron_history": [
                {
                    "name": str(entry.get("name", "")),
                    "status": str(entry.get("status", "")),
                    "started_at": entry.get("started_at"),
                    "ended_at": entry.get("ended_at"),
                    "returncode": entry.get("returncode"),
                }
                for entry in load_history(limit=25)
            ],
            "scheduler_running": is_scheduler_running(),
        }

    def _knowledge(self) -> dict[str, Any]:
        memories = scan_memory_files(
            self.cwd,
            max_files=100,
            include_disabled=True,
            include_expired=True,
        )
        return {
            "memories": [
                {
                    "id": memory.id or memory.relative_path,
                    "title": _short(memory.title, 200),
                    "description": _short(memory.description, 500),
                    "preview": _short(memory.body_preview, 500),
                    "type": memory.memory_type,
                    "category": memory.category,
                    "importance": memory.importance,
                    "source": memory.source,
                    "tags": list(memory.tags)[:20],
                    "modified_at": memory.modified_at,
                    "disabled": memory.disabled,
                }
                for memory in memories
            ],
            "limits": {"returned": len(memories), "maximum": 100},
        }

    def _autopilot(self) -> dict[str, Any]:
        if not get_project_autopilot_registry_path(self.cwd).exists():
            return {"initialized": False, "stats": {}, "cards": [], "journal": []}
        store = RepoAutopilotStore(self.cwd)
        cards = store.list_cards()[:100]
        return {
            "initialized": True,
            "stats": store.stats(),
            "cards": [
                {
                    "id": card.id,
                    "title": _short(card.title, 200),
                    "body": _short(card.body, 500),
                    "source_kind": card.source_kind,
                    "source_ref": _short(card.source_ref, 120),
                    "status": card.status,
                    "score": card.score,
                    "labels": card.labels[:20],
                    "updated_at": card.updated_at,
                }
                for card in cards
            ],
            "journal": [
                {
                    "timestamp": entry.timestamp,
                    "kind": entry.kind,
                    "summary": _short(entry.summary, 500),
                    "task_id": entry.task_id,
                }
                for entry in store.load_journal(limit=25)
            ],
        }


def known_web_actions() -> tuple[str, ...]:
    return tuple(_ACTION_MODELS)
