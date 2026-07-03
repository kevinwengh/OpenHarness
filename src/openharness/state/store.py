"""Observable application state store.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from openharness.state.app_state import AppState


Listener = Callable[[AppState], None]


class AppStateStore:
    """Very small observable state store.

    Integration: Constructed or referenced by ``_make_command_context``, ``build_runtime``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self, initial_state: AppState) -> None:
        """Initialize ``AppStateStore`` and bind its runtime dependencies.

        Integration: Exposed through ``AppStateStore``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._state = initial_state
        self._listeners: list[Listener] = []

    def get(self) -> AppState:
        """Return the current state snapshot.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self._state

    def set(self, **updates) -> AppState:
        """Update the state and notify listeners.

        Integration: Exposed through ``AppStateStore`` and collaborates with ``listener``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._state = replace(self._state, **updates)
        for listener in list(self._listeners):
            listener(self._state)
        return self._state

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Register a listener and return an unsubscribe callback.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_listeners.append``, ``_listeners.remove``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._listeners.append(listener)

        def _unsubscribe() -> None:
            """Apply unsubscribe to the enclosing subsystem state.

            Integration: Used as an internal helper or callback at this module boundary and
            collaborates with ``_listeners.remove``.

            Concurrency: This is synchronous; preserve deterministic behavior for its direct
            callers.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _unsubscribe
