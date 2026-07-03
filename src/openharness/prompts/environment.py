"""Environment detection for system prompt construction.

Gathers OS, shell, platform, working directory, date, and git info.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class EnvironmentInfo:
    """Snapshot of the current runtime environment.

    Integration: Constructed or referenced by ``get_environment_info``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    os_name: str
    os_version: str
    platform_machine: str
    shell: str
    cwd: str
    home_dir: str
    date: str
    python_version: str
    python_executable: str
    virtual_env: str | None
    is_git_repo: bool
    git_branch: str | None = None
    hostname: str = ""
    extra: dict[str, str] = field(default_factory=dict)


def detect_os() -> tuple[str, str]:
    """Return (os_name, os_version) for the current platform.

    Integration: Called by ``get_environment_info`` and collaborates with ``platform.system``,
    ``platform.release``, ``platform.mac_ver``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers;
    retain lock scope and release behavior.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    system = platform.system()
    if system == "Linux":
        try:
            import distro  # type: ignore[import-untyped]
            return "Linux", distro.version(pretty=True) or platform.release()
        except ImportError:
            return "Linux", platform.release()
    elif system == "Darwin":
        mac_ver = platform.mac_ver()[0]
        return "macOS", mac_ver or platform.release()
    elif system == "Windows":
        win_ver = platform.version()
        return "Windows", win_ver
    return system, platform.release()


def detect_shell() -> str:
    """Detect the user's shell.

    Integration: Called by ``get_environment_info`` and collaborates with ``os.environ.get``,
    ``shutil.which``, ``Path``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    shell = os.environ.get("SHELL", "")
    if shell:
        return Path(shell).name

    # Fallback: check for common shells on PATH
    for candidate in ("bash", "zsh", "fish", "sh"):
        if shutil.which(candidate):
            return candidate

    return "unknown"


def detect_git_info(cwd: str) -> tuple[bool, str | None]:
    """Check if cwd is inside a git repo and return (is_git_repo, branch_name).

    Integration: Called by ``get_environment_info`` and collaborates with ``subprocess.run``,
    ``result.stdout.strip``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve argv boundaries, timeouts, and child cleanup; preserve exception and
    fallback behavior expected by callers.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
        is_git = result.returncode == 0 and result.stdout.strip() == "true"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, None

    if not is_git:
        return False, None

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
        branch = result.stdout.strip() if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        branch = None

    return True, branch


def get_environment_info(cwd: str | None = None) -> EnvironmentInfo:
    """Gather all environment information into an EnvironmentInfo snapshot.

    Integration: Called by ``build_system_prompt`` and collaborates with ``os.environ.get``,
    ``detect_os``, ``detect_shell``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if cwd is None:
        cwd = os.getcwd()

    python_executable = str(Path(sys.executable).resolve())
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if not virtual_env:
        executable_path = Path(python_executable)
        candidate = executable_path.parent.parent
        if executable_path.parent.name in {"bin", "Scripts"} and (candidate / "pyvenv.cfg").exists():
            virtual_env = str(candidate)

    os_name, os_version = detect_os()
    shell = detect_shell()
    is_git, branch = detect_git_info(cwd)

    return EnvironmentInfo(
        os_name=os_name,
        os_version=os_version,
        platform_machine=platform.machine(),
        shell=shell,
        cwd=cwd,
        home_dir=str(Path.home()),
        date=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
        python_version=platform.python_version(),
        python_executable=python_executable,
        virtual_env=virtual_env,
        is_git_repo=is_git,
        git_branch=branch,
        hostname=platform.node(),
    )
