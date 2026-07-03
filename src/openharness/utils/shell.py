"""Shared shell and subprocess helpers.

Integration: This module participates in the shared OpenHarness runtime.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from openharness.config import Settings, load_settings
from openharness.platforms import PlatformName, get_platform
from openharness.sandbox import wrap_command_for_sandbox


def resolve_shell_command(
    command: str,
    *,
    platform_name: PlatformName | None = None,
    prefer_pty: bool = False,
) -> list[str]:
    """Return argv for the best available shell on the current platform.

    Integration: Called by ``create_shell_subprocess`` and collaborates with ``shutil.which``,
    ``get_platform``, ``os.environ.get``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    resolved_platform = platform_name or get_platform()
    if resolved_platform == "windows":
        bash = shutil.which("bash")
        if bash and _bash_is_usable(bash):
            return [bash, "-lc", command]
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell:
            return [powershell, "-NoLogo", "-NoProfile", "-Command", command]
        return [shutil.which("cmd.exe") or "cmd.exe", "/d", "/s", "/c", command]

    bash = shutil.which("bash")
    if bash:
        argv = [bash, "-lc", command]
        if prefer_pty:
            wrapped = _wrap_command_with_script(argv, platform_name=resolved_platform)
            if wrapped is not None:
                return wrapped
        return argv
    shell = shutil.which("sh") or os.environ.get("SHELL") or "/bin/sh"
    argv = [shell, "-lc", command]
    if prefer_pty:
        wrapped = _wrap_command_with_script(argv, platform_name=resolved_platform)
        if wrapped is not None:
            return wrapped
    return argv


async def create_shell_subprocess(
    command: str,
    *,
    cwd: str | Path,
    settings: Settings | None = None,
    prefer_pty: bool = False,
    stdin: int | None = asyncio.subprocess.DEVNULL,
    stdout: int | None = None,
    stderr: int | None = None,
    env: Mapping[str, str] | None = None,
) -> asyncio.subprocess.Process:
    """Spawn a shell command with platform-aware shell selection and sandboxing.

    Integration: Called by
    ``TestShellIntegration.test_create_shell_subprocess_routes_through_docker``,
    ``TestShellIntegration.test_create_shell_subprocess_routes_through_docker._run`` and
    collaborates with ``resolve_shell_command``, ``wrap_command_for_sandbox``,
    ``load_settings``.

    Event loop: This coroutine coordinates child tasks; preserve cancellation, completion, and
    exception ownership.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    argv boundaries, timeouts, and child cleanup; preserve exception and fallback behavior
    expected by callers.
    """
    resolved_settings = settings or load_settings()

    # Docker backend: route through docker exec
    if resolved_settings.sandbox.enabled and resolved_settings.sandbox.backend == "docker":
        from openharness.sandbox.session import get_docker_sandbox

        session = get_docker_sandbox()
        if session is not None and session.is_running:
            argv = resolve_shell_command(command)
            return await session.exec_command(
                argv,
                cwd=cwd,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                env=dict(env) if env is not None else None,
            )
        if resolved_settings.sandbox.fail_if_unavailable:
            from openharness.sandbox import SandboxUnavailableError

            raise SandboxUnavailableError("Docker sandbox session is not running")

    # Existing srt path
    argv = resolve_shell_command(command, prefer_pty=prefer_pty)
    argv, cleanup_path = wrap_command_for_sandbox(argv, settings=resolved_settings)

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(Path(cwd).resolve()),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            env=dict(env) if env is not None else None,
        )
    except Exception:
        if cleanup_path is not None:
            cleanup_path.unlink(missing_ok=True)
        raise

    if cleanup_path is not None:
        asyncio.create_task(_cleanup_after_exit(process, cleanup_path))
    return process


def _wrap_command_with_script(
    argv: list[str],
    *,
    platform_name: PlatformName | None = None,
) -> list[str] | None:
    """Derive wrap command with script from the current inputs and subsystem state.

    Integration: Called by ``resolve_shell_command`` and collaborates with ``shutil.which``,
    ``get_platform``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    resolved_platform = platform_name or get_platform()
    if resolved_platform == "macos":
        return None
    script = shutil.which("script")
    if script is None:
        return None
    if len(argv) >= 3 and argv[1] == "-lc":
        return [script, "-qefc", argv[2], "/dev/null"]
    return None


def _bash_is_usable(bash_path: str) -> bool:
    """Return True when a discovered bash executable can run commands.

    On Windows, ``shutil.which("bash")`` can find WSL's ``bash.exe`` even when no
    WSL distribution is installed. In that case the executable exists but every
    command fails, so fall back to PowerShell/cmd instead of selecting it.

    Integration: Called by ``resolve_shell_command`` and collaborates with ``subprocess.run``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve argv boundaries, timeouts, and child cleanup; preserve exception and
    fallback behavior expected by callers.
    """
    try:
        result = subprocess.run(
            [bash_path, "-lc", "exit 0"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


async def _cleanup_after_exit(process: asyncio.subprocess.Process, cleanup_path: Path) -> None:
    """Clean up after exit for the enclosing subsystem.

    Integration: Called by ``create_shell_subprocess`` and collaborates with
    ``cleanup_path.unlink``, ``process.wait``.

    Event loop: This coroutine coordinates child tasks; preserve cancellation, completion, and
    exception ownership.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    try:
        await process.wait()
    finally:
        cleanup_path.unlink(missing_ok=True)
