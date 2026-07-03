"""Load keybindings from config.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

from pathlib import Path

from openharness.config.paths import get_config_dir
from openharness.keybindings.parser import parse_keybindings
from openharness.keybindings.resolver import resolve_keybindings


def get_keybindings_path() -> Path:
    """Return the user keybindings path.

    Integration: Called by ``create_default_command_registry``,
    ``create_default_command_registry._keybindings_handler`` and collaborates with
    ``get_config_dir``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_config_dir() / "keybindings.json"


def load_keybindings() -> dict[str, str]:
    """Load and merge keybindings.

    Integration: Called by ``create_default_command_registry``,
    ``create_default_command_registry._keybindings_handler`` and collaborates with
    ``get_keybindings_path``, ``resolve_keybindings``, ``path.exists``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    path = get_keybindings_path()
    if not path.exists():
        return resolve_keybindings()
    return resolve_keybindings(parse_keybindings(path.read_text(encoding="utf-8")))
