"""Cross-platform exclusive file-lock helpers.

Used to serialise read-modify-write sequences on shared JSON registries
(credentials, settings, cron, memory index, swarm mailbox). Pair with
:func:`openharness.utils.fs.atomic_write_text` to make each critical section
both race-free and crash-safe.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from openharness.platforms import PlatformName, get_platform


class SwarmLockError(RuntimeError):
    """Base error for file-lock failures.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """


class SwarmLockUnavailableError(SwarmLockError):
    """Raised when file locking is unavailable on the current platform.

    Integration: Constructed or referenced by ``exclusive_file_lock``,
    ``_exclusive_posix_lock``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """


@contextmanager
def exclusive_file_lock(
    lock_path: Path,
    *,
    platform_name: PlatformName | None = None,
) -> Iterator[None]:
    """Acquire an exclusive file lock for the duration of the context.

    Integration: Called by ``add_memory_entry``, ``remove_memory_entry`` and collaborates with
    ``SwarmLockUnavailableError``, ``get_platform``, ``_exclusive_windows_lock``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking; retain lock scope and release behavior.

    Change safety: Preserve yield ordering and partial-consumption behavior; preserve exception
    and fallback behavior expected by callers.
    """
    resolved_platform = platform_name or get_platform()
    if resolved_platform == "windows":
        with _exclusive_windows_lock(lock_path):
            yield
        return
    if resolved_platform in {"macos", "linux", "wsl"}:
        with _exclusive_posix_lock(lock_path):
            yield
        return
    raise SwarmLockUnavailableError(
        f"file locking is not supported on platform {resolved_platform!r}"
    )


@contextmanager
def _exclusive_posix_lock(lock_path: Path) -> Iterator[None]:
    """Apply exclusive posix lock to the enclosing subsystem state.

    Integration: Called by ``exclusive_file_lock`` and collaborates with
    ``lock_path.parent.mkdir``, ``lock_path.touch``, ``lock_path.open``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers;
    retain lock scope and release behavior.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    yield ordering and partial-consumption behavior; preserve exception and fallback behavior
    expected by callers.
    """
    try:
        import fcntl
    except ImportError as exc:
        raise SwarmLockUnavailableError(f"fcntl not available: {exc}") from exc

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _exclusive_windows_lock(lock_path: Path) -> Iterator[None]:
    """Apply exclusive windows lock to the enclosing subsystem state.

    Integration: Called by ``exclusive_file_lock`` and collaborates with
    ``lock_path.parent.mkdir``, ``lock_path.open``, ``lock_file.seek``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers;
    retain lock scope and release behavior.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    yield ordering and partial-consumption behavior; preserve exception and fallback behavior
    expected by callers.
    """
    try:
        import msvcrt
    except ImportError as exc:
        raise SwarmLockUnavailableError(f"msvcrt not available: {exc}") from exc

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        # msvcrt.locking requires a byte range to exist and the file be open
        # in binary mode. Lock the first byte for the lifetime of the
        # critical section.
        lock_file.seek(0)
        if lock_path.stat().st_size == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
