"""Theme configuration schema.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ColorsConfig(BaseModel):
    """Color configuration for a theme.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    primary: str = "#5875d4"
    secondary: str = "#4a9eff"
    accent: str = "#61afef"
    error: str = "#e06c75"
    muted: str = "#5c6370"
    background: str = "#282c34"
    foreground: str = "#abb2bf"


class BorderConfig(BaseModel):
    """Border style configuration.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    style: Literal["rounded", "single", "double", "none"] = "rounded"
    char: str | None = None


class IconConfig(BaseModel):
    """Icon/glyph configuration.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    spinner: str = "⠋"
    tool: str = "⚙"
    error: str = "✖"
    success: str = "✔"
    agent: str = "◆"


class LayoutConfig(BaseModel):
    """Layout configuration.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    compact: bool = False
    show_tokens: bool = True
    show_time: bool = True


class ThemeConfig(BaseModel):
    """Full theme configuration.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    name: str
    colors: ColorsConfig = ColorsConfig()
    borders: BorderConfig = BorderConfig()
    icons: IconConfig = IconConfig()
    layout: LayoutConfig = LayoutConfig()
