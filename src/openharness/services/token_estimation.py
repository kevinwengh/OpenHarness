"""Simple token estimation utilities.

Integration: This module participates in runtime support services such as compaction, sessions,
cron, extraction, and autodream.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve persistence schemas, task/time bounds, compaction continuity,
cancellation, atomic writes, and best-effort failure boundaries.
"""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Estimate tokens from plain text using a rough character heuristic.

    Integration: Called by ``estimate_message_tokens``, ``microcompact_messages``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def estimate_message_tokens(messages: list[str]) -> int:
    """Estimate tokens for a collection of message strings.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``estimate_tokens``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return sum(estimate_tokens(message) for message in messages)
