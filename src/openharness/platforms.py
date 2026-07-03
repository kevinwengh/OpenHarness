"""Platform and capability detection helpers.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Mapping

PlatformName = Literal["macos", "linux", "windows", "wsl", "unknown"]


@dataclass(frozen=True)
class PlatformCapabilities:
    """Capabilities that drive shell, swarm, and sandbox decisions.

    Integration: Constructed or referenced by ``get_platform_capabilities``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    name: PlatformName
    supports_posix_shell: bool
    supports_native_windows_shell: bool
    supports_tmux: bool
    supports_swarm_mailbox: bool
    supports_sandbox_runtime: bool
    supports_docker_sandbox: bool


def detect_platform(
    *,
    system_name: str | None = None,
    release: str | None = None,
    env: Mapping[str, str] | None = None,
) -> PlatformName:
    """Return the normalized platform name for the current process.

    Integration: Called by ``get_platform`` and collaborates with ``lower``, ``env_map.get``,
    ``platform.system``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers;
    retain lock scope and release behavior.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    env_map = env or os.environ
    system = (system_name or platform.system()).lower()
    kernel_release = (release or platform.release()).lower()

    if system == "darwin":
        return "macos"
    if system in {"windows", "win32"}:
        return "windows"
    if system == "linux":
        if "microsoft" in kernel_release or env_map.get("WSL_DISTRO_NAME") or env_map.get("WSL_INTEROP"):
            return "wsl"
        return "linux"
    return "unknown"


@lru_cache(maxsize=1)
def get_platform() -> PlatformName:
    """Return the detected platform for this process.

    Integration: Called by ``get_platform_capabilities``, ``get_sandbox_availability`` and
    collaborates with ``lru_cache``, ``detect_platform``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return detect_platform()


def get_platform_capabilities(platform_name: PlatformName | None = None) -> PlatformCapabilities:
    """Return the capability matrix for a normalized platform name.

    Integration: Called by ``get_sandbox_availability``, ``get_docker_availability`` and
    collaborates with ``PlatformCapabilities``, ``get_platform``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    name = platform_name or get_platform()
    if name in {"macos", "linux", "wsl"}:
        return PlatformCapabilities(
            name=name,
            supports_posix_shell=True,
            supports_native_windows_shell=False,
            supports_tmux=True,
            supports_swarm_mailbox=True,
            supports_sandbox_runtime=True,
            supports_docker_sandbox=True,
        )
    if name == "windows":
        return PlatformCapabilities(
            name=name,
            supports_posix_shell=False,
            supports_native_windows_shell=True,
            supports_tmux=False,
            supports_swarm_mailbox=False,
            supports_sandbox_runtime=False,
            supports_docker_sandbox=False,
        )
    return PlatformCapabilities(
        name=name,
        supports_posix_shell=False,
        supports_native_windows_shell=False,
        supports_tmux=False,
        supports_swarm_mailbox=False,
        supports_sandbox_runtime=False,
        supports_docker_sandbox=False,
    )
