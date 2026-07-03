"""Voice mode keyterm extraction.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

import re


def extract_keyterms(text: str) -> list[str]:
    """Extract likely key terms from a transcript.

    Integration: Called by ``create_default_command_registry``,
    ``create_default_command_registry._voice_handler`` and collaborates with ``token.lower``,
    ``re.findall``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return sorted({token.lower() for token in re.findall(r"[A-Za-z0-9_]{4,}", text)})
