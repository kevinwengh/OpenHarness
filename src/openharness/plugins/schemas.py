"""Plugin manifest schemas.

Integration: This module participates in manifest-driven discovery of optional skills, commands,
agents, tools, hooks, and MCP servers.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve project-plugin opt-in trust, import isolation, precedence, namespacing,
and actionable load failures.
"""

from __future__ import annotations

from pydantic import BaseModel


class PluginManifest(BaseModel):
    """Plugin manifest stored in plugin.json or .claude-plugin/plugin.json.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    name: str
    version: str = "0.0.0"
    description: str = ""
    enabled_by_default: bool = True
    skills_dir: str = "skills"
    tools_dir: str = "tools"
    hooks_file: str = "hooks.json"
    mcp_file: str = "mcp.json"
    # Extended fields: optional author, commands, agents, etc.
    author: dict | None = None
    commands: str | list | dict | None = None
    agents: str | list | None = None
    skills: str | list | None = None
    hooks: str | dict | list | None = None
