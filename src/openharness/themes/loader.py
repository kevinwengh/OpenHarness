"""Theme loading utilities.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from openharness.themes.builtin import BUILTIN_THEMES
from openharness.themes.schema import ThemeConfig

logger = logging.getLogger(__name__)


def get_custom_themes_dir() -> Path:
    """Return the user custom themes directory.

    Integration: Called by ``load_custom_themes`` and collaborates with ``path.mkdir``,
    ``Path.home``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    path = Path.home() / ".openharness" / "themes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_custom_themes() -> dict[str, ThemeConfig]:
    """Load custom themes from ~/.openharness/themes/*.json.

    Integration: Called by ``list_themes``, ``load_theme`` and collaborates with ``glob``,
    ``json.loads``, ``ThemeConfig.model_validate``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    exception and fallback behavior expected by callers.
    """
    themes: dict[str, ThemeConfig] = {}
    for path in sorted(get_custom_themes_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            theme = ThemeConfig.model_validate(data)
            themes[theme.name] = theme
        except Exception as exc:
            logger.debug("Skipping invalid theme file %s: %s", path, exc)
    return themes


def list_themes() -> list[str]:
    """Return names of all available themes (builtin + custom).

    Integration: Called by ``create_default_command_registry``,
    ``create_default_command_registry._theme_handler`` and collaborates with
    ``load_custom_themes``, ``BUILTIN_THEMES.keys``, ``names.append``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    names = list(BUILTIN_THEMES.keys())
    for name in load_custom_themes():
        if name not in names:
            names.append(name)
    return names


def load_theme(name: str) -> ThemeConfig:
    """Load a theme by name.

    Looks up custom themes first, then falls back to builtins.
    Raises ``KeyError`` if the theme is not found.

    Integration: Called by ``create_default_command_registry``,
    ``create_default_command_registry._theme_handler`` and collaborates with
    ``load_custom_themes``, ``KeyError``, ``list_themes``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    custom = load_custom_themes()
    if name in custom:
        return custom[name]
    if name in BUILTIN_THEMES:
        return BUILTIN_THEMES[name]
    raise KeyError(f"Unknown theme: {name!r}. Available: {list_themes()}")
