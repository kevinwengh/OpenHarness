"""In-process workflow concurrency-key coordination."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Literal

ConcurrencyPolicy = Literal["serialize", "drop", "cancel_previous"]


@dataclass(frozen=True)
class ConcurrencyLease:
    """Result yielded after applying one rendered concurrency-key policy."""

    key: str
    policy: ConcurrencyPolicy
    acquired: bool
    reason: str = ""


@dataclass
class _Entry:
    """Reference-counted lock and current owner for one in-process key."""

    lock: asyncio.Lock
    users: int = 0
    owner: asyncio.Task | None = None


class WorkflowConcurrencyCoordinator:
    """Serialize, drop, or replace active runs sharing a rendered key.

    Event loop: All state belongs to the loop that created the coordinator.
    Cancellation releases both the per-key lock and its reference count.

    Change safety: Never await a cancelled owner while holding ``_guard``; the
    owner needs that guard to release its key in the context-manager ``finally``.
    """

    def __init__(self, *, cancel_timeout: float = 3.0) -> None:
        """Initialize loop-local key state with a bounded replacement timeout."""

        if cancel_timeout <= 0:
            raise ValueError("cancel_timeout must be positive")
        self._cancel_timeout = cancel_timeout
        self._guard = asyncio.Lock()
        self._entries: dict[str, _Entry] = {}

    @asynccontextmanager
    async def slot(
        self,
        key: str,
        policy: ConcurrencyPolicy,
    ) -> AsyncIterator[ConcurrencyLease]:
        """Acquire a key according to ``serialize``, ``drop``, or replacement policy.

        The yielded lease may be unacquired for non-blocking policies. Callers
        must inspect ``lease.acquired`` before performing effects.
        """

        if policy not in {"serialize", "drop", "cancel_previous"}:
            raise ValueError(f"unsupported concurrency policy: {policy}")
        if not key:
            yield ConcurrencyLease(key, policy, True)
            return
        current = asyncio.current_task()
        if current is None:
            raise RuntimeError("workflow concurrency requires an asyncio task")

        entry = await self._retain(key)
        acquired = False
        try:
            if policy == "drop":
                busy = False
                async with self._guard:
                    if entry.lock.locked():
                        busy = True
                    else:
                        await entry.lock.acquire()
                        entry.owner = current
                        acquired = True
                if busy:
                    yield ConcurrencyLease(key, policy, False, "concurrency key is busy")
                    return
            elif policy == "cancel_previous":
                async with self._guard:
                    owner = entry.owner
                    if owner is not None and owner is not current and not owner.done():
                        owner.cancel()
                try:
                    await asyncio.wait_for(entry.lock.acquire(), timeout=self._cancel_timeout)
                except asyncio.TimeoutError:
                    yield ConcurrencyLease(
                        key,
                        policy,
                        False,
                        "previous workflow did not release the concurrency key",
                    )
                    return
                async with self._guard:
                    entry.owner = current
                    acquired = True
            else:
                await entry.lock.acquire()
                async with self._guard:
                    entry.owner = current
                    acquired = True
            yield ConcurrencyLease(key, policy, True)
        finally:
            if acquired:
                async with self._guard:
                    if entry.owner is current:
                        entry.owner = None
                    if entry.lock.locked():
                        entry.lock.release()
            await self._release(key, entry)

    async def _retain(self, key: str) -> _Entry:
        """Return and retain the shared entry for a rendered key."""

        async with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                entry = _Entry(lock=asyncio.Lock())
                self._entries[key] = entry
            entry.users += 1
            return entry

    async def _release(self, key: str, entry: _Entry) -> None:
        """Drop one user and remove an idle entry without racing new acquirers."""

        async with self._guard:
            entry.users -= 1
            if entry.users == 0 and not entry.lock.locked() and entry.owner is None:
                self._entries.pop(key, None)
