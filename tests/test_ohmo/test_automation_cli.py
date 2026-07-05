from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from ohmo.cli import app
from ohmo.workspace import initialize_workspace


runner = CliRunner()


def _write_workflow(workspace: Path) -> None:
    (workspace / "automations" / "remember.yaml").write_text(
        """\
version: 1
id: remember-event
trigger: {event: manual.note}
policy:
  allowed_actions: [knowledge.upsert]
  knowledge_namespaces: [notes]
steps:
  - id: remember
    type: action
    action: knowledge.upsert
    with:
      namespace: notes
      title: '${event.payload.title}'
      content: '${event.payload.content}'
""",
        encoding="utf-8",
    )


def _write_event(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "id": "manual-note-1",
                "type": "manual.note",
                "occurred_at": datetime(2026, 7, 5, tzinfo=timezone.utc).isoformat(),
                "source": {"adapter": "cli"},
                "actor": {"id": "local-operator"},
                "payload": {"title": "CLI note", "content": "Remembered from CLI"},
                "metadata": {"api_key": "must-not-display"},
            }
        ),
        encoding="utf-8",
    )


def _write_approval_workflow(workspace: Path) -> None:
    (workspace / "automations" / "approval.yaml").write_text(
        """\
version: 1
id: approve-event
source_behavior: consume
trigger: {event: manual.approval}
policy: {allowed_actions: []}
steps:
  - id: approval
    type: approval
    prompt: Approve the manual event?
    approver_ids: [LOCAL_APPROVER]
""",
        encoding="utf-8",
    )


def test_automation_validate_list_show_and_dry_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    workspace = initialize_workspace(tmp_path / "workspace")
    _write_workflow(workspace)
    event = tmp_path / "event.json"
    _write_event(event)

    validated = runner.invoke(
        app,
        ["automation", "validate", "--workspace", str(workspace), "--cwd", str(tmp_path)],
    )
    listed = runner.invoke(app, ["automation", "list", "--workspace", str(workspace)])
    shown = runner.invoke(
        app,
        ["automation", "show", "remember-event", "--workspace", str(workspace)],
    )
    tested = runner.invoke(
        app,
        [
            "automation",
            "test",
            "remember-event",
            "--event",
            str(event),
            "--workspace",
            str(workspace),
        ],
    )

    assert validated.exit_code == 0
    assert "Validated 1 workflow(s); 0 invalid" in validated.output
    assert listed.exit_code == 0 and "remember-event" in listed.output
    assert shown.exit_code == 0 and '"knowledge.upsert"' in shown.output
    assert tested.exit_code == 0 and '"matched": true' in tested.output
    assert not list((workspace / "automation" / "runs").glob("*.json"))


def test_automation_run_runs_and_inspect_redact_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    workspace = initialize_workspace(tmp_path / "workspace")
    _write_workflow(workspace)
    event = tmp_path / "event.json"
    _write_event(event)

    executed = runner.invoke(
        app,
        [
            "automation",
            "run",
            "remember-event",
            "--event",
            str(event),
            "--workspace",
            str(workspace),
            "--cwd",
            str(tmp_path),
        ],
    )
    assert executed.exit_code == 0, executed.output
    payload = json.loads(executed.output)
    run_id = payload["run"]["id"]
    assert payload["run"]["status"] == "completed"
    assert payload["run"]["event"]["metadata"]["api_key"] == "[REDACTED]"

    runs = runner.invoke(app, ["automation", "runs", "--workspace", str(workspace)])
    inspected = runner.invoke(
        app,
        ["automation", "inspect", run_id, "--workspace", str(workspace)],
    )

    assert runs.exit_code == 0 and "completed=1" in runs.output
    assert inspected.exit_code == 0
    assert "must-not-display" not in inspected.output
    assert "[REDACTED]" in inspected.output
    assert (workspace / "memory" / "notes_cli_note.md").exists()


def test_automation_validate_reports_invalid_definition(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    workspace = initialize_workspace(tmp_path / "workspace")
    (workspace / "automations" / "invalid.yaml").write_text(
        "version: 99\nid: invalid\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["automation", "validate", "--workspace", str(workspace), "--cwd", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "1 invalid definition(s)" in result.output


def test_automation_local_approval_requires_allowed_actor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    workspace = initialize_workspace(tmp_path / "workspace")
    _write_approval_workflow(workspace)
    event = tmp_path / "approval-event.json"
    event.write_text(
        json.dumps(
            {
                "version": 1,
                "id": "manual-approval-1",
                "type": "manual.approval",
                "occurred_at": "2026-07-05T12:00:00Z",
                "source": {"adapter": "cli"},
                "actor": {"id": "local"},
            }
        ),
        encoding="utf-8",
    )
    created = runner.invoke(
        app,
        [
            "automation",
            "run",
            "approve-event",
            "--event",
            str(event),
            "--workspace",
            str(workspace),
            "--cwd",
            str(tmp_path),
        ],
    )
    assert created.exit_code == 0, created.output
    run_id = json.loads(created.output)["run"]["id"]

    denied = runner.invoke(
        app,
        [
            "automation",
            "approve",
            run_id,
            "--actor",
            "ATTACKER",
            "--workspace",
            str(workspace),
            "--cwd",
            str(tmp_path),
        ],
    )
    approved = runner.invoke(
        app,
        [
            "automation",
            "approve",
            run_id,
            "--actor",
            "LOCAL_APPROVER",
            "--workspace",
            str(workspace),
            "--cwd",
            str(tmp_path),
        ],
    )

    assert denied.exit_code == 1
    assert "not allowed to approve" in denied.output
    assert approved.exit_code == 0
    assert json.loads(approved.output)["status"] == "completed"


def test_automation_help_lists_management_commands() -> None:
    result = runner.invoke(app, ["automation", "--help"])

    assert result.exit_code == 0
    for command in (
        "validate",
        "list",
        "show",
        "test",
        "run",
        "runs",
        "inspect",
        "retry",
        "cancel",
        "approve",
        "reject",
    ):
        assert command in result.output
