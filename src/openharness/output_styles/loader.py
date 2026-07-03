"""Output style loading.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openharness.config.paths import get_config_dir


@dataclass(frozen=True)
class OutputStyle:
    """A named output style.

    Integration: Constructed or referenced by ``load_output_styles``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    name: str
    content: str
    source: str


def get_output_styles_dir() -> Path:
    """Return the custom output styles directory.

    Integration: Called by ``load_output_styles`` and collaborates with ``path.mkdir``,
    ``get_config_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    path = get_config_dir() / "output_styles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_output_styles() -> list[OutputStyle]:
    """Load bundled and custom output styles.

    Integration: Called by ``create_default_command_registry``,
    ``create_default_command_registry._output_style_handler`` and collaborates with
    ``OutputStyle``, ``glob``, ``styles.append``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    styles = [
        OutputStyle(name="default", content="Standard rich console output.", source="builtin"),
        OutputStyle(name="minimal", content="Very terse plain-text output.", source="builtin"),
        OutputStyle(name="codex", content="Codex-like compact transcript and tool output.", source="builtin"),
    ]
    for path in sorted(get_output_styles_dir().glob("*.md")):
        styles.append(
            OutputStyle(
                name=path.stem,
                content=path.read_text(encoding="utf-8"),
                source="user",
            )
        )
    return styles
