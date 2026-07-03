"""Input helpers built on prompt_toolkit.

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


class InputSession:
    """Async prompt wrapper.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Event loop: Async methods ``prompt``, ``ask`` run on their caller's loop; instances must
    retain clear task, cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self) -> None:
        """Initialize ``InputSession`` and bind its runtime dependencies.

        Integration: Exposed through ``InputSession`` and collaborates with ``PromptSession``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._session = PromptSession()
        self._prompt = "> "

    def set_modes(self, *, vim_enabled: bool, voice_enabled: bool) -> None:
        """Update prompt decorations for active modes.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``join``, ``parts.append``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        parts: list[str] = []
        if vim_enabled:
            parts.append("[vim]")
        if voice_enabled:
            parts.append("[voice]")
        prefix = "".join(parts)
        self._prompt = f"{prefix}> " if prefix else "> "

    async def prompt(self) -> str:
        """Prompt the user for one line of input.

        Integration: Called by ``_text_prompt``, ``_select_from_menu`` and collaborates with
        ``_session.prompt_async``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return await self._session.prompt_async(self._prompt)

    async def ask(self, question: str) -> str:
        """Prompt the user for an ad-hoc answer.

        Integration: Called by ``_select_with_questionary``, ``_confirm_prompt`` and
        collaborates with ``_session.prompt_async``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        prompt = f"[question] {question}\n> "
        return await self._session.prompt_async(prompt)
