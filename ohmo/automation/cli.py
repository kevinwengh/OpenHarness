"""Local operator CLI for Ohmo automation definitions and durable runs."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import typer

from openharness.automation.loader import load_workflow_definitions
from openharness.automation.matcher import evaluate_condition, match_workflow
from openharness.automation.models import ActionStep, AutomationEvent
from openharness.automation.store import AutomationStore
from openharness.automation.templates import TemplateRenderError, render_template
from openharness.channels.bus.queue import MessageBus

from ohmo.automation.service import OhmoAutomationService
from ohmo.gateway.config import load_gateway_config
from ohmo.workspace import (
    get_automation_state_dir,
    get_automations_dir,
    initialize_workspace,
)

automation_app = typer.Typer(name="automation", help="Manage Ohmo automation workflows")
_WORKSPACE_HELP = "Path to the ohmo workspace (defaults to ~/.ohmo)"
_SECRET_PARTS = (
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{10,}|gh[pousr]_[A-Za-z0-9]{16,}|AKIA[A-Z0-9]{16})"
)


def _workspace(value: str | None) -> Path:
    return initialize_workspace(value)


def _definitions(root: Path):
    return load_workflow_definitions(get_automations_dir(root))


def _definition(root: Path, workflow_id: str):
    loaded = _definitions(root)
    for definition in loaded.definitions:
        if definition.id == workflow_id:
            return definition
    typer.echo(f"Automation workflow not found: {workflow_id}", err=True)
    raise typer.Exit(1)


def _event(path: str) -> AutomationEvent:
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        return AutomationEvent.model_validate_json(text)
    except Exception as exc:
        typer.echo(f"Cannot load automation event: {exc}", err=True)
        raise typer.Exit(1) from exc


def _store(root: Path) -> AutomationStore:
    return AutomationStore(get_automation_state_dir(root))


def _json(value: Any) -> str:
    return json.dumps(_redact_and_bound(value), indent=2, ensure_ascii=False, default=str)


def _redact_and_bound(value: Any, *, key: object | None = None, depth: int = 0) -> Any:
    if depth > 24:
        return "[TRUNCATED]"
    if key is not None:
        normalized = str(key).lower().replace("-", "_")
        if any(part in normalized for part in _SECRET_PARTS):
            return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): _redact_and_bound(item, key=item_key, depth=depth + 1)
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_and_bound(item, depth=depth + 1) for item in value[:256]]
    if isinstance(value, str):
        if value.lower().startswith(("bearer ", "basic ")):
            return "[REDACTED]"
        redacted = _SECRET_VALUE_RE.sub("[REDACTED]", value)
        return redacted if len(redacted) <= 4000 else redacted[:4000] + "…[TRUNCATED]"
    return value


def _service(root: Path, cwd: str) -> OhmoAutomationService:
    return OhmoAutomationService(
        workspace=root,
        cwd=Path(cwd).resolve(),
        bus=MessageBus(),
        provider_profile=load_gateway_config(root).provider_profile,
    )


@automation_app.command("validate")
def validate_cmd(
    cwd: str = typer.Option(str(Path.cwd()), "--cwd"),
    workspace: str | None = typer.Option(None, "--workspace", help=_WORKSPACE_HELP),
) -> None:
    root = _workspace(workspace)
    service = _service(root, cwd)
    asyncio.run(service.validate_configuration())
    for diagnostic in service.diagnostics:
        typer.echo(f"{diagnostic.path}: {diagnostic.message}", err=True)
    typer.echo(
        f"Validated {len(service.definitions)} workflow(s); "
        f"{len(service.diagnostics)} invalid definition(s)."
    )
    if service.diagnostics:
        raise typer.Exit(1)


@automation_app.command("list")
def list_cmd(
    workspace: str | None = typer.Option(None, "--workspace", help=_WORKSPACE_HELP),
) -> None:
    loaded = _definitions(_workspace(workspace))
    for definition in loaded.definitions:
        typer.echo(
            f"{definition.id}\t{'enabled' if definition.enabled else 'disabled'}\t"
            f"priority={definition.priority}\tbehavior={definition.source_behavior}"
        )
    if not loaded.definitions:
        typer.echo("No valid automation workflows found.")


@automation_app.command("show")
def show_cmd(
    workflow_id: str = typer.Argument(...),
    workspace: str | None = typer.Option(None, "--workspace", help=_WORKSPACE_HELP),
) -> None:
    definition = _definition(_workspace(workspace), workflow_id)
    typer.echo(_json(definition.model_dump(mode="json", by_alias=True)))


@automation_app.command("test")
def test_cmd(
    workflow_id: str = typer.Argument(...),
    event: str = typer.Option(..., "--event", help="JSON event path, or - for stdin"),
    workspace: str | None = typer.Option(None, "--workspace", help=_WORKSPACE_HELP),
) -> None:
    root = _workspace(workspace)
    definition = _definition(root, workflow_id)
    parsed_event = _event(event)
    trace = match_workflow(definition, parsed_event)
    context = {
        "event": parsed_event.model_dump(mode="json"),
        "run": {},
        "steps": {},
    }
    rendered_steps = []
    for step in definition.steps:
        step_condition = None
        if step.when is not None:
            matched, outcomes = evaluate_condition(step.when, context)
            step_condition = {
                "matched": matched,
                "outcomes": [outcome.__dict__ for outcome in outcomes],
            }
        if not isinstance(step, ActionStep):
            rendered_steps.append({"id": step.id, "type": step.type, "condition": step_condition})
            continue
        try:
            rendered = render_template(step.arguments, context)
        except TemplateRenderError as exc:
            rendered = {"render_error": str(exc)}
        rendered_steps.append(
            {
                "id": step.id,
                "type": step.type,
                "action": step.action,
                "condition": step_condition,
                "arguments": rendered,
            }
        )
    typer.echo(
        _json(
            {
                "workflow_id": definition.id,
                "matched": trace.matched,
                "outcomes": [outcome.__dict__ for outcome in trace.outcomes],
                "rendered_action_steps": rendered_steps,
            }
        )
    )


@automation_app.command("run")
def run_cmd(
    workflow_id: str = typer.Argument(...),
    event: str = typer.Option(..., "--event", help="JSON event path, or - for stdin"),
    cwd: str = typer.Option(str(Path.cwd()), "--cwd"),
    workspace: str | None = typer.Option(None, "--workspace", help=_WORKSPACE_HELP),
) -> None:
    root = _workspace(workspace)
    parsed_event = _event(event)

    async def run() -> dict[str, Any]:
        service = _service(root, cwd)
        try:
            dispatch = await service.submit_workflow(workflow_id, parsed_event)
            await service.drain()
            run_state = service.store.load_run(dispatch.run_ids[0])
            queued = []
            while not service.bus.outbound.empty():
                message = service.bus.outbound.get_nowait()
                queued.append(
                    {
                        "channel": message.channel,
                        "chat_id": message.chat_id,
                        "content": message.content,
                    }
                )
            return {"run": run_state.model_dump(mode="json"), "queued_messages": queued}
        finally:
            await service.stop()

    try:
        result = asyncio.run(run())
    except Exception as exc:
        typer.echo(f"Automation run failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(_json(result))


@automation_app.command("runs")
def runs_cmd(
    status: str | None = typer.Option(None, "--status"),
    workspace: str | None = typer.Option(None, "--workspace", help=_WORKSPACE_HELP),
) -> None:
    runs = _store(_workspace(workspace)).list_runs(status=status)
    counts = Counter(run.status for run in runs)
    typer.echo(" ".join(f"{name}={counts[name]}" for name in sorted(counts)) or "runs=0")
    for run in runs:
        typer.echo(f"{run.id}\t{run.workflow_id}\t{run.status}\t{run.updated_at.isoformat()}")


@automation_app.command("inspect")
def inspect_cmd(
    run_id: str = typer.Argument(...),
    workspace: str | None = typer.Option(None, "--workspace", help=_WORKSPACE_HELP),
) -> None:
    try:
        run = _store(_workspace(workspace)).load_run(run_id)
    except Exception as exc:
        typer.echo(f"Cannot inspect automation run: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(_json(run.model_dump(mode="json", by_alias=True)))


def _mutate_run(
    operation: str,
    run_id: str,
    *,
    workspace: str | None,
    cwd: str,
    actor: str | None = None,
    reason: str | None = None,
    allow_unknown_outcome: bool = False,
) -> None:
    root = _workspace(workspace)

    async def mutate():
        service = _service(root, cwd)
        try:
            await service.start()
            if operation == "retry":
                await service.retry_run(
                    run_id,
                    allow_unknown_outcome=allow_unknown_outcome,
                )
            elif operation == "cancel":
                await service.cancel_run(run_id, reason=reason or "cancelled by local operator")
            else:
                if not actor:
                    raise ValueError("--actor is required for approval decisions")
                await service.resolve_approval(
                    run_id,
                    actor_id=actor,
                    approved=operation == "approve",
                    reason=reason,
                )
            await service.drain()
            return service.store.load_run(run_id)
        finally:
            await service.stop()

    try:
        result = asyncio.run(mutate())
    except Exception as exc:
        typer.echo(f"Automation {operation} failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(_json(result.model_dump(mode="json")))


@automation_app.command("retry")
def retry_cmd(
    run_id: str = typer.Argument(...),
    allow_unknown_outcome: bool = typer.Option(False, "--allow-unknown-outcome"),
    cwd: str = typer.Option(str(Path.cwd()), "--cwd"),
    workspace: str | None = typer.Option(None, "--workspace", help=_WORKSPACE_HELP),
) -> None:
    _mutate_run(
        "retry",
        run_id,
        workspace=workspace,
        cwd=cwd,
        allow_unknown_outcome=allow_unknown_outcome,
    )


@automation_app.command("cancel")
def cancel_cmd(
    run_id: str = typer.Argument(...),
    reason: str = typer.Option("cancelled by local operator", "--reason"),
    cwd: str = typer.Option(str(Path.cwd()), "--cwd"),
    workspace: str | None = typer.Option(None, "--workspace", help=_WORKSPACE_HELP),
) -> None:
    _mutate_run("cancel", run_id, workspace=workspace, cwd=cwd, reason=reason)


@automation_app.command("approve")
def approve_cmd(
    run_id: str = typer.Argument(...),
    actor: str = typer.Option(..., "--actor"),
    cwd: str = typer.Option(str(Path.cwd()), "--cwd"),
    workspace: str | None = typer.Option(None, "--workspace", help=_WORKSPACE_HELP),
) -> None:
    _mutate_run("approve", run_id, workspace=workspace, cwd=cwd, actor=actor)


@automation_app.command("reject")
def reject_cmd(
    run_id: str = typer.Argument(...),
    actor: str = typer.Option(..., "--actor"),
    reason: str | None = typer.Option(None, "--reason"),
    cwd: str = typer.Option(str(Path.cwd()), "--cwd"),
    workspace: str | None = typer.Option(None, "--workspace", help=_WORKSPACE_HELP),
) -> None:
    _mutate_run(
        "reject",
        run_id,
        workspace=workspace,
        cwd=cwd,
        actor=actor,
        reason=reason,
    )
