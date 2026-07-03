"""Interactive permission prompt.

Integration: This module participates in runtime composition and adapters for CLI, React,
Textual, headless, and ohmo callers.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve startup/readiness, protocol ordering, callback ownership, interruption,
persistence, and resource cleanup.
"""

from __future__ import annotations

from prompt_toolkit import PromptSession


async def ask_permission(tool_name: str, reason: str) -> bool:
    """Prompt the user to approve a mutating tool.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``PromptSession``, ``session.prompt_async``, ``lower``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    session = PromptSession()
    response = await session.prompt_async(
        f"Allow tool '{tool_name}'? [{reason}] [y/N]: "
    )
    return response.strip().lower() in {"y", "yes"}
