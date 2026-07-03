"""Voice mode helpers and diagnostics.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from openharness.api.provider import ProviderInfo


@dataclass(frozen=True)
class VoiceDiagnostics:
    """Basic voice mode capability summary.

    Integration: Constructed or referenced by ``inspect_voice_capabilities``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    available: bool
    reason: str
    recorder: str | None = None


def toggle_voice_mode(enabled: bool) -> bool:
    """Toggle voice mode state.

    Integration: Exposed as a public entrypoint for this subsystem.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return not enabled


def inspect_voice_capabilities(provider: ProviderInfo) -> VoiceDiagnostics:
    """Return a coarse voice capability summary for the current environment.

    Integration: Called by ``create_default_command_registry``,
    ``create_default_command_registry._voice_handler`` and collaborates with
    ``VoiceDiagnostics``, ``shutil.which``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    recorder = shutil.which("sox") or shutil.which("ffmpeg") or shutil.which("arecord")
    if not provider.voice_supported:
        return VoiceDiagnostics(
            available=False,
            reason=provider.voice_reason,
            recorder=recorder,
        )
    if recorder is None:
        return VoiceDiagnostics(
            available=False,
            reason="no supported recorder found (expected sox, ffmpeg, or arecord)",
        )
    return VoiceDiagnostics(
        available=True,
        reason="voice shell is available",
        recorder=recorder,
    )
