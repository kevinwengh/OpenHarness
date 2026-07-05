"""Bounded resource and allowlisted action contracts for the local web UI."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openharness.api.usage import UsageSnapshot
from openharness.config.paths import get_project_autopilot_registry_path
from openharness.memory.manager import add_memory_entry
from openharness.services.cron import load_cron_jobs, upsert_cron_job
from openharness.services.session_backend import DEFAULT_SESSION_BACKEND
from openharness.ui.web_resources import WebResourceService, known_web_actions


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENHARNESS_LOGS_DIR", str(tmp_path / "logs"))


def test_capabilities_are_bounded_and_do_not_import_blocked_project_plugins(tmp_path: Path):
    project = tmp_path / "repo"
    plugin = project / ".openharness" / "plugins" / "blocked"
    tools = plugin / "tools"
    tools.mkdir(parents=True)
    marker = tmp_path / "imported.txt"
    (plugin / "plugin.json").write_text(
        json.dumps({"name": "blocked", "version": "1.0.0", "description": "Blocked"}),
        encoding="utf-8",
    )
    (tools / "unsafe.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n",
        encoding="utf-8",
    )

    snapshot = WebResourceService(project).snapshot("capabilities")

    assert snapshot.area == "capabilities"
    assert snapshot.data["tools"]
    assert snapshot.data["commands"]
    assert snapshot.data["trust"] == {
        "project_plugins_allowed": False,
        "blocked_project_plugin_directories": 1,
    }
    assert not marker.exists()
    assert len(snapshot.data["tools"]) <= 200


def test_capabilities_degrade_when_credential_status_is_unavailable(tmp_path: Path, monkeypatch):
    project = tmp_path / "repo"
    project.mkdir()

    class _UnavailableAuth:
        def __init__(self, settings):
            del settings

        def get_profile_statuses(self):
            raise RuntimeError("credential-store-secret")

    monkeypatch.setattr("openharness.ui.web_resources.AuthManager", _UnavailableAuth)

    snapshot = WebResourceService(project).snapshot("capabilities")

    assert snapshot.data["tools"]
    assert snapshot.data["providers"]
    assert all(profile["auth_state"] == "unknown" for profile in snapshot.data["providers"])


def test_knowledge_returns_metadata_not_raw_paths(tmp_path: Path):
    project = tmp_path / "repo"
    project.mkdir()
    add_memory_entry(project, "Preferred stack", "Use Python for backend services", tags=("python",))

    snapshot = WebResourceService(project).snapshot("knowledge")

    memory = snapshot.data["memories"][0]
    assert memory["title"] == "Preferred stack"
    assert "Python" in memory["description"]
    assert memory["tags"] == ["python"]
    assert "path" not in memory
    assert snapshot.data["limits"]["maximum"] == 100


def test_sessions_return_bounded_summaries_not_conversation_payloads(tmp_path: Path):
    project = tmp_path / "repo"
    project.mkdir()
    backend = DEFAULT_SESSION_BACKEND
    backend.save_snapshot(
        cwd=project,
        model="test-model",
        system_prompt="system-secret",
        messages=[],
        usage=UsageSnapshot(),
        session_id="session-one",
        tool_metadata={"api_key": "tool-secret"},
    )

    snapshot = WebResourceService(project).snapshot("sessions")

    assert snapshot.data["sessions"][0]["id"] == "session-one"
    serialized = snapshot.model_dump_json()
    assert "messages" not in serialized
    assert "system-secret" not in serialized
    assert "tool-secret" not in serialized
    assert "path" not in serialized
    assert snapshot.data["limits"]["maximum"] == 20


def test_sessions_omit_noncanonical_resume_identifiers(tmp_path: Path):
    class _SessionBackend:
        def list_snapshots(self, cwd, limit):
            del cwd, limit
            return [
                {"session_id": "safe-session", "summary": "Safe", "message_count": 1},
                {"session_id": "bad\n/permissions full_auto", "summary": "Unsafe", "message_count": 1},
            ]

    bundle = SimpleNamespace(session_backend=_SessionBackend())
    snapshot = WebResourceService(tmp_path).snapshot("sessions", runtime_bundle=bundle)

    assert [item["id"] for item in snapshot.data["sessions"]] == ["safe-session"]
    assert snapshot.data["limits"]["returned"] == 1


def test_autopilot_read_does_not_initialize_missing_state(tmp_path: Path):
    project = tmp_path / "repo"
    project.mkdir()
    registry = get_project_autopilot_registry_path(project)

    snapshot = WebResourceService(project).snapshot("autopilot")

    assert snapshot.data["initialized"] is False
    assert not registry.exists()


@pytest.mark.asyncio
async def test_actions_are_explicit_and_cron_toggle_uses_owner(tmp_path: Path):
    project = tmp_path / "repo"
    project.mkdir()
    upsert_cron_job({"name": "digest", "schedule": "0 */8 * * *", "type": "prompt"})
    service = WebResourceService(project)

    result = await service.action("cron.toggle", {"name": "digest", "enabled": False})

    assert result.action == "cron.toggle"
    assert result.resource == {"name": "digest", "enabled": False}
    assert load_cron_jobs()[0]["enabled"] is False
    assert known_web_actions() == (
        "task.stop",
        "bridge.stop",
        "cron.toggle",
        "cron.run",
        "autopilot.enqueue",
    )
    with pytest.raises(KeyError):
        await service.action("python.call", {"name": "anything"})


@pytest.mark.asyncio
async def test_autopilot_enqueue_validates_and_uses_store(tmp_path: Path):
    project = tmp_path / "repo"
    project.mkdir()
    service = WebResourceService(project)

    result = await service.action(
        "autopilot.enqueue",
        {"title": "Add browser coverage", "body": "Cover the local workbench."},
    )

    assert result.resource is not None
    assert result.resource["status"] == "queued"
    snapshot = service.snapshot("autopilot")
    assert snapshot.data["initialized"] is True
    assert snapshot.data["cards"][0]["title"] == "Add browser coverage"
    with pytest.raises(ValueError):
        await service.action("autopilot.enqueue", {"title": "", "unexpected": True})
