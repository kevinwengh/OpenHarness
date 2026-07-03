"""Plugin installation helpers.

Integration: This module participates in manifest-driven discovery of optional skills, commands,
agents, tools, hooks, and MCP servers.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve project-plugin opt-in trust, import isolation, precedence, namespacing,
and actionable load failures.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from openharness.plugins.loader import get_user_plugins_dir


def _resolve_user_plugin_dir(name: str) -> Path:
    """Resolve a user plugin name to a direct child of the plugin directory.

    Integration: Called by ``uninstall_plugin`` and collaborates with ``resolve``,
    ``ValueError``, ``get_user_plugins_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if not name or name != Path(name).name or "\\" in name:
        raise ValueError("invalid plugin name")

    plugins_dir = get_user_plugins_dir().resolve()
    path = (plugins_dir / name).resolve()
    if path.parent != plugins_dir:
        raise ValueError("invalid plugin name")
    return path


def install_plugin_from_path(source: str | Path) -> Path:
    """Install a plugin directory into the user plugin directory.

    Integration: Called by ``_run_plugin_flow``, ``plugin_install`` and collaborates with
    ``resolve``, ``dest.exists``, ``shutil.copytree``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    src = Path(source).resolve()
    dest = get_user_plugins_dir() / src.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


def uninstall_plugin(name: str) -> bool:
    """Remove a user plugin by directory name.

    Integration: Called by ``_run_plugin_flow``, ``plugin_uninstall`` and collaborates with
    ``_resolve_user_plugin_dir``, ``shutil.rmtree``, ``path.exists``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    path = _resolve_user_plugin_dir(name)
    if not path.exists():
        return False
    shutil.rmtree(path)
    return True
