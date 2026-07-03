"""Backwards-compatible re-export of the generic file-lock helpers.

The implementation lives in :mod:`openharness.utils.file_lock`. This module
is retained so existing callers (swarm mailbox, permission sync, external
plugins) keep working without changes.

Integration: This module participates in multi-agent team, mailbox, permission, subprocess, and
worktree coordination.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve identity and mailbox schemas, lock/atomicity, cancellation, permission
routing, Git isolation, and teardown.
"""

from __future__ import annotations

from openharness.utils.file_lock import (
    SwarmLockError,
    SwarmLockUnavailableError,
    _exclusive_posix_lock,
    _exclusive_windows_lock,
    exclusive_file_lock,
)

__all__ = [
    "SwarmLockError",
    "SwarmLockUnavailableError",
    "_exclusive_posix_lock",
    "_exclusive_windows_lock",
    "exclusive_file_lock",
]
