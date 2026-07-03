"""Best-effort hot reloading for settings-backed hooks.

Integration: This module participates in extension callbacks around sessions, prompts,
compaction, tools, notifications, and stopping.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve priority/order, blocking semantics, timeouts, untrusted arguments,
failure policy, and async lifecycle.
"""

from __future__ import annotations

from pathlib import Path

from openharness.config import load_settings
from openharness.hooks.loader import HookRegistry, load_hook_registry


class HookReloader:
    """Reload hook definitions when the settings file changes.

    Integration: Constructed or referenced by ``build_runtime``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self, settings_path: Path) -> None:
        """Initialize ``HookReloader`` and bind its runtime dependencies.

        Integration: Exposed through ``HookReloader`` and collaborates with ``HookRegistry``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._settings_path = settings_path
        self._last_mtime_ns = -1
        self._registry = HookRegistry()

    def current_registry(self) -> HookRegistry:
        """Return the latest registry, reloading if needed.

        Integration: Called by ``build_runtime`` and collaborates with ``_settings_path.stat``,
        ``load_hook_registry``, ``HookRegistry``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        try:
            stat = self._settings_path.stat()
        except FileNotFoundError:
            self._registry = HookRegistry()
            self._last_mtime_ns = -1
            return self._registry

        if stat.st_mtime_ns != self._last_mtime_ns:
            self._last_mtime_ns = stat.st_mtime_ns
            self._registry = load_hook_registry(load_settings(self._settings_path))
        return self._registry
