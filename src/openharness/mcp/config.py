"""Load MCP server config from settings and plugins.

Integration: This module participates in external MCP transports adapted into the normal
tool/resource registry.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve transport lifecycle, authentication, namespacing, JSON schemas, errors,
and shared permission/tool replay.
"""

from __future__ import annotations

from openharness.plugins.types import LoadedPlugin


def load_mcp_server_configs(settings, plugins: list[LoadedPlugin]) -> dict[str, object]:
    """Merge settings and plugin MCP server configs.

    Integration: Called by ``_run_scenario``, ``_run_plugin_flow`` and collaborates with
    ``plugin.mcp_servers.items``, ``servers.setdefault``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    servers = dict(settings.mcp_servers)
    for plugin in plugins:
        if not plugin.enabled:
            continue
        for name, config in plugin.mcp_servers.items():
            servers.setdefault(f"{plugin.manifest.name}:{name}", config)
    return servers
