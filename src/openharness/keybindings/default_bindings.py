"""Default keybinding map.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations


DEFAULT_KEYBINDINGS: dict[str, str] = {
    "ctrl+l": "clear",
    "ctrl+k": "toggle_vim",
    "ctrl+v": "toggle_voice",
    "ctrl+t": "tasks",
}
