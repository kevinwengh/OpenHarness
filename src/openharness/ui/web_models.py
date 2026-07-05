"""Presentation-safe models for the local OpenHarness web UI.

The browser receives bounded status snapshots rather than serialized runtime or
settings objects. Keep this module free of web-framework concerns so redaction
and schema behavior can be tested directly.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from openharness.auth.manager import AuthManager
from openharness.config import Settings, load_settings


class WebAppInfo(BaseModel):
    """Identify the local application without exposing host process details."""

    name: str = "OpenHarness"
    version: str


class WebWorkspaceInfo(BaseModel):
    """Describe the project currently in scope for the local browser session."""

    name: str
    path: str


class WebAuthInfo(BaseModel):
    """Expose only whether authentication is usable, never credential material."""

    state: Literal["configured", "missing", "unknown"]
    label: str


class WebRuntimeInfo(BaseModel):
    """Summarize the effective runtime settings needed for first render."""

    profile: str
    provider: str
    model: str
    auth: WebAuthInfo
    permission_mode: str
    sandbox_enabled: bool
    sandbox_backend: str
    effort: str
    max_turns: int


class WebNavigationItem(BaseModel):
    """Describe one stable product area and its current support depth."""

    id: Literal[
        "overview",
        "workbench",
        "sessions",
        "runtime",
        "capabilities",
        "work",
        "knowledge",
        "autopilot",
    ]
    label: str
    description: str
    path: str
    depth: Literal["operate", "configure", "inspect"]
    availability: Literal["available", "coming_soon"]


class WebBootstrap(BaseModel):
    """Versioned, credential-redacted initial payload for the browser shell."""

    schema_version: Literal[1] = 1
    app: WebAppInfo
    workspace: WebWorkspaceInfo
    runtime: WebRuntimeInfo
    navigation: list[WebNavigationItem] = Field(max_length=16)


_NAVIGATION = (
    WebNavigationItem(
        id="overview",
        label="Overview",
        description="Local runtime health and product surface",
        path="/",
        depth="inspect",
        availability="available",
    ),
    WebNavigationItem(
        id="workbench",
        label="Workbench",
        description="Converse with and supervise the active agent",
        path="/workbench",
        depth="operate",
        availability="coming_soon",
    ),
    WebNavigationItem(
        id="sessions",
        label="Sessions",
        description="Resume and organize project conversations",
        path="/sessions",
        depth="operate",
        availability="coming_soon",
    ),
    WebNavigationItem(
        id="runtime",
        label="Runtime",
        description="Provider, model, permission, and sandbox controls",
        path="/runtime",
        depth="configure",
        availability="coming_soon",
    ),
    WebNavigationItem(
        id="capabilities",
        label="Capabilities",
        description="Tools, skills, plugins, hooks, and MCP",
        path="/capabilities",
        depth="inspect",
        availability="coming_soon",
    ),
    WebNavigationItem(
        id="work",
        label="Work",
        description="Background tasks, bridges, and schedules",
        path="/work",
        depth="operate",
        availability="coming_soon",
    ),
    WebNavigationItem(
        id="knowledge",
        label="Knowledge",
        description="Project and session memory",
        path="/knowledge",
        depth="inspect",
        availability="coming_soon",
    ),
    WebNavigationItem(
        id="autopilot",
        label="Autopilot",
        description="Repository work intake and run health",
        path="/autopilot",
        depth="operate",
        availability="coming_soon",
    ),
)


def _package_version() -> str:
    try:
        return version("openharness-ai")
    except PackageNotFoundError:
        return "0.0.0+local"


def build_web_bootstrap(
    cwd: str | Path,
    *,
    settings: Settings | None = None,
    auth_manager: AuthManager | None = None,
) -> WebBootstrap:
    """Build the bounded browser bootstrap snapshot from canonical settings owners."""

    workspace = Path(cwd).expanduser().resolve()
    effective_settings = settings or load_settings()
    profile_name, profile = effective_settings.resolve_profile()
    manager = auth_manager or AuthManager(effective_settings)

    auth_state: Literal["configured", "missing", "unknown"] = "unknown"
    auth_label = profile.auth_source
    try:
        status = manager.get_profile_statuses().get(profile_name)
        if status is not None:
            auth_state = "configured" if bool(status.get("configured")) else "missing"
            auth_label = str(status.get("auth_source") or profile.auth_source)
    except Exception:
        # Status inspection must not prevent the local shell from loading. The
        # browser gets an explicit unknown state and never the exception detail,
        # which could contain storage or credential-path information.
        auth_state = "unknown"

    return WebBootstrap(
        app=WebAppInfo(version=_package_version()),
        workspace=WebWorkspaceInfo(name=workspace.name or str(workspace), path=str(workspace)),
        runtime=WebRuntimeInfo(
            profile=profile_name,
            provider=profile.provider,
            model=effective_settings.model,
            auth=WebAuthInfo(state=auth_state, label=auth_label),
            permission_mode=effective_settings.permission.mode.value,
            sandbox_enabled=effective_settings.sandbox.enabled,
            sandbox_backend=effective_settings.sandbox.backend,
            effort=effective_settings.effort,
            max_turns=effective_settings.max_turns,
        ),
        navigation=[item.model_copy(deep=True) for item in _NAVIGATION],
    )
