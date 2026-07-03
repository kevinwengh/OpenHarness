"""Tool-output context budget helpers.

Integration: This module participates in runtime support services such as compaction, sessions,
cron, extraction, and autodream.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve persistence schemas, task/time bounds, compaction continuity,
cancellation, atomic writes, and best-effort failure boundaries.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

DEFAULT_TOOL_OUTPUT_INLINE_CHARS = 16_000
DEFAULT_TOOL_OUTPUT_PREVIEW_CHARS = 3_000
DEFAULT_MICROCOMPACT_TOOL_RESULT_CHARS = 4_000


def _read_positive_int_env(name: str, default: int, *, minimum: int = 1) -> int:
    """Read positive int env for the enclosing subsystem.

    Integration: Called by ``tool_output_inline_chars``, ``tool_output_preview_chars`` and
    collaborates with ``strip``, ``os.environ.get``, ``log.warning``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        log.warning("Ignoring invalid %s=%r", name, raw)
        return default


def tool_output_inline_chars() -> int:
    """Derive tool output inline chars from the current inputs and subsystem state.

    Integration: Called by ``_offload_tool_output_if_needed`` and collaborates with
    ``_read_positive_int_env``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return _read_positive_int_env(
        "OPENHARNESS_TOOL_OUTPUT_INLINE_CHARS",
        DEFAULT_TOOL_OUTPUT_INLINE_CHARS,
        minimum=256,
    )


def tool_output_preview_chars() -> int:
    """Derive tool output preview chars from the current inputs and subsystem state.

    Integration: Called by ``_offload_tool_output_if_needed`` and collaborates with
    ``_read_positive_int_env``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return _read_positive_int_env(
        "OPENHARNESS_TOOL_OUTPUT_PREVIEW_CHARS",
        DEFAULT_TOOL_OUTPUT_PREVIEW_CHARS,
        minimum=128,
    )


def microcompact_tool_result_chars() -> int:
    """Derive microcompact tool result chars from the current inputs and subsystem state.

    Integration: Called by ``is_microcompactable_tool_result`` and collaborates with
    ``_read_positive_int_env``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return _read_positive_int_env(
        "OPENHARNESS_MICROCOMPACT_TOOL_RESULT_CHARS",
        DEFAULT_MICROCOMPACT_TOOL_RESULT_CHARS,
        minimum=256,
    )


def is_microcompactable_tool_result(tool_name: str, content: str) -> bool:
    """Return True when a tool result should be eligible for old-result clearing.

    Integration: Called by ``_collect_compactable_tool_ids`` and collaborates with
    ``tool_name.strip``, ``normalized.startswith``, ``microcompact_tool_result_chars``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    normalized = tool_name.strip()
    if normalized.startswith("mcp__"):
        return True
    return len(content) >= microcompact_tool_result_chars()
