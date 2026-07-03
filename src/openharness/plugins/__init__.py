"""Plugin exports.

Integration: This module participates in manifest-driven discovery of optional skills, commands,
agents, tools, hooks, and MCP servers.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve project-plugin opt-in trust, import isolation, precedence, namespacing,
and actionable load failures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from openharness.plugins.schemas import PluginManifest
    from openharness.plugins.types import LoadedPlugin

__all__ = [
    "LoadedPlugin",
    "PluginManifest",
    "discover_plugin_paths",
    "get_project_plugins_dir",
    "get_user_plugins_dir",
    "install_plugin_from_path",
    "load_plugins",
    "uninstall_plugin",
]


def __getattr__(name: str):
    """Resolve a lazily exported attribute from ``this module``.

    Integration: Used as an internal helper or callback at this module boundary and collaborates
    with ``AttributeError``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if name in {"discover_plugin_paths", "get_project_plugins_dir", "get_user_plugins_dir", "load_plugins"}:
        from openharness.plugins.loader import (
            discover_plugin_paths,
            get_project_plugins_dir,
            get_user_plugins_dir,
            load_plugins,
        )

        return {
            "discover_plugin_paths": discover_plugin_paths,
            "get_project_plugins_dir": get_project_plugins_dir,
            "get_user_plugins_dir": get_user_plugins_dir,
            "load_plugins": load_plugins,
        }[name]
    if name in {"install_plugin_from_path", "uninstall_plugin"}:
        from openharness.plugins.installer import install_plugin_from_path, uninstall_plugin

        return {
            "install_plugin_from_path": install_plugin_from_path,
            "uninstall_plugin": uninstall_plugin,
        }[name]
    if name == "PluginManifest":
        from openharness.plugins.schemas import PluginManifest

        return PluginManifest
    if name == "LoadedPlugin":
        from openharness.plugins.types import LoadedPlugin

        return LoadedPlugin
    raise AttributeError(name)
