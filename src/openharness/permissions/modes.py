"""Permission mode definitions.

Integration: This module participates in tool policy evaluation before execution.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve sensitive-path denial, command/path normalization, mode defaults,
confirmation semantics, and conservative read-only classification.
"""

from __future__ import annotations

from enum import Enum


class PermissionMode(str, Enum):
    """Supported permission modes.

    Integration: Constructed or referenced by ``create_default_command_registry``,
    ``create_default_command_registry._permissions_handler``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve persisted and wire-visible values or provide an explicit migration
    for stored configuration and messages.
    """

    DEFAULT = "default"
    PLAN = "plan"
    FULL_AUTO = "full_auto"
