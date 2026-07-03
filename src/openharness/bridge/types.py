"""Bridge configuration types.

Integration: This module participates in external command/session bridges exposed to runtime and
UI status.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve subprocess lifecycle, output files, session identity, interruption, and
cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DEFAULT_SESSION_TIMEOUT_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class WorkData:
    """Work item metadata.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    type: Literal["session", "healthcheck"]
    id: str


@dataclass(frozen=True)
class WorkSecret:
    """Decoded work secret.

    Integration: Constructed or referenced by ``_run_bridge_flow``, ``decode_work_secret``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    version: int
    session_ingress_token: str
    api_base_url: str


@dataclass(frozen=True)
class BridgeConfig:
    """Minimal bridge configuration.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    dir: str
    machine_name: str
    max_sessions: int = 1
    verbose: bool = False
    session_timeout_ms: int = DEFAULT_SESSION_TIMEOUT_MS
