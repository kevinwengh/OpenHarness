"""Plugin runtime types.

Integration: This module participates in manifest-driven discovery of optional skills, commands,
agents, tools, hooks, and MCP servers.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve project-plugin opt-in trust, import isolation, precedence, namespacing,
and actionable load failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from openharness.coordinator.agent_definitions import AgentDefinition
from openharness.mcp.types import McpServerConfig
from openharness.plugins.schemas import PluginManifest
from openharness.skills.types import SkillDefinition

if TYPE_CHECKING:
    from openharness.automation.actions import AutomationAction
    from openharness.tools.base import BaseTool


@dataclass(frozen=True)
class PluginCommandDefinition:
    """A slash command contributed by a plugin.

    Integration: Constructed or referenced by ``_load_plugin_commands``,
    ``_load_commands_from_directory``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    name: str
    description: str
    content: str
    path: str | None = None
    source: str = "plugin"
    base_dir: str | None = None
    argument_hint: str | None = None
    when_to_use: str | None = None
    version: str | None = None
    model: str | None = None
    effort: str | int | None = None
    disable_model_invocation: bool = False
    user_invocable: bool = True
    is_skill: bool = False
    display_name: str | None = None


@dataclass(frozen=True)
class LoadedPlugin:
    """A loaded plugin and its contributed artifacts.

    Integration: Constructed or referenced by ``load_plugin``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    manifest: PluginManifest
    path: Path
    enabled: bool
    skills: list[SkillDefinition] = field(default_factory=list)
    commands: list[PluginCommandDefinition] = field(default_factory=list)
    agents: list[AgentDefinition] = field(default_factory=list)
    tools: list[BaseTool] = field(default_factory=list)
    automation_actions: list[AutomationAction] = field(default_factory=list)
    hooks: dict[str, list] = field(default_factory=dict)
    mcp_servers: dict[str, McpServerConfig] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """Derive name from the current inputs and subsystem state.

        Integration: Called by ``FeishuChannel._create_managed_group_sync``,
        ``FeishuChannel._rename_group_sync``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self.manifest.name

    @property
    def description(self) -> str:
        """Derive description from the current inputs and subsystem state.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self.manifest.description
