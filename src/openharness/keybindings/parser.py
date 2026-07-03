"""Keybinding file parsing.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

import json


def parse_keybindings(text: str) -> dict[str, str]:
    """Parse a JSON keybinding mapping.

    Integration: Called by ``load_keybindings`` and collaborates with ``json.loads``,
    ``data.items``, ``ValueError``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("keybindings file must be a JSON object")
    parsed: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("keybindings keys and values must be strings")
        parsed[key] = value
    return parsed
