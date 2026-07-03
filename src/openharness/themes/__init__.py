"""Theme system exports.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from openharness.themes.loader import list_themes, load_custom_themes, load_theme
from openharness.themes.schema import (
    BorderConfig,
    ColorsConfig,
    IconConfig,
    LayoutConfig,
    ThemeConfig,
)

__all__ = [
    "BorderConfig",
    "ColorsConfig",
    "IconConfig",
    "LayoutConfig",
    "ThemeConfig",
    "list_themes",
    "load_custom_themes",
    "load_theme",
]
