"""Keybinding resolution.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

from openharness.keybindings.default_bindings import DEFAULT_KEYBINDINGS


def resolve_keybindings(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Merge user overrides over the default keybindings.

    Integration: Called by ``load_keybindings`` and collaborates with ``resolved.update``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    resolved = dict(DEFAULT_KEYBINDINGS)
    if overrides:
        resolved.update(overrides)
    return resolved
