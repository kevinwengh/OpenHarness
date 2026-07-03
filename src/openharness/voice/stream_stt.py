"""Placeholder streaming STT interface.

Integration: This module participates in the shared OpenHarness runtime.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations


async def transcribe_stream(_: bytes) -> str:
    """Return a placeholder message for unimplemented STT.

    Integration: Exposed as a public entrypoint for this subsystem.

    Event loop: This coroutine executes synchronously until it returns; filesystem or process
    work therefore runs inline on the caller's loop. Keep that work bounded or offload it before
    it can block.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return "Streaming STT is not configured in this build."
