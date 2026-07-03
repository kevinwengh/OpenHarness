"""Docker-based sandbox backend for isolated tool execution.

Integration: This module participates in isolated execution selected by runtime/tool adapters.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve path validation, container lifecycle, network/resource limits, command
fidelity, and cleanup.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from openharness.config import Settings
from openharness.platforms import get_platform, get_platform_capabilities
from openharness.sandbox.adapter import SandboxAvailability, SandboxUnavailableError

logger = logging.getLogger(__name__)


def get_docker_availability(settings: Settings) -> SandboxAvailability:
    """Check whether Docker can be used as a sandbox backend.

    Integration: Called by ``TestContainerLifecycle.test_availability_check``,
    ``start_docker_sandbox`` and collaborates with ``get_platform``,
    ``get_platform_capabilities``, ``shutil.which``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve argv boundaries, timeouts, and child cleanup; preserve exception and
    fallback behavior expected by callers.
    """
    if not settings.sandbox.enabled or settings.sandbox.backend != "docker":
        return SandboxAvailability(
            enabled=False, available=False, reason="Docker sandbox is not enabled"
        )

    platform_name = get_platform()
    capabilities = get_platform_capabilities(platform_name)
    if not capabilities.supports_docker_sandbox:
        return SandboxAvailability(
            enabled=True,
            available=False,
            reason=f"Docker sandbox is not supported on platform {platform_name}",
        )

    docker = shutil.which("docker")
    if not docker:
        return SandboxAvailability(
            enabled=True,
            available=False,
            reason="Docker CLI not found; install Docker Desktop or Docker Engine",
        )

    try:
        subprocess.run(
            [docker, "info"],
            capture_output=True,
            timeout=5,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return SandboxAvailability(
            enabled=True,
            available=False,
            reason="Docker daemon is not running",
            command=docker,
        )

    return SandboxAvailability(enabled=True, available=True, command=docker)


@dataclass
class DockerSandboxSession:
    """Manages a long-running Docker container for one OpenHarness session.

    Integration: Constructed or referenced by ``TestContainerLifecycle.test_start_and_stop``,
    ``TestContainerLifecycle.test_stop_sync``.

    Event loop: Async methods ``start``, ``stop``, ``exec_command`` run on their caller's loop;
    instances must retain clear task, cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    settings: Settings
    session_id: str
    cwd: Path
    _container_name: str = field(init=False)
    _running: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        """Apply post init to the enclosing subsystem state.

        Integration: Used as an internal helper or callback at this module boundary.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._container_name = f"openharness-sandbox-{self.session_id}"

    @property
    def container_name(self) -> str:
        """Derive container name from the current inputs and subsystem state.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self._container_name

    @property
    def is_running(self) -> bool:
        """Return whether running for the enclosing subsystem.

        Integration: Exposed through ``DockerSandboxSession``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self._running

    def _build_run_argv(self) -> list[str]:
        """Build the ``docker run`` argv for container creation.

        Integration: Called by ``DockerSandboxSession.start`` and collaborates with
        ``argv.extend``, ``docker_cfg.extra_env.items``, ``shutil.which``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        docker = shutil.which("docker") or "docker"
        sandbox = self.settings.sandbox
        docker_cfg = sandbox.docker
        cwd_str = str(self.cwd.resolve())

        argv = [
            docker,
            "run",
            "-d",
            "--rm",
            "--name",
            self._container_name,
        ]

        # Docker backend currently supports only fully disabled networking.
        # Domain-level allow/deny policies exist for the srt backend, but Docker
        # does not enforce them yet. Fail closed instead of silently widening
        # egress to unrestricted bridge networking.
        if sandbox.network.allowed_domains or sandbox.network.denied_domains:
            logger.warning(
                "Docker sandbox does not enforce allowed_domains/denied_domains yet; "
                "keeping network disabled"
            )
        argv.extend(["--network", "none"])

        # Resource limits
        if docker_cfg.cpu_limit > 0:
            argv.extend(["--cpus", str(docker_cfg.cpu_limit)])
        if docker_cfg.memory_limit:
            argv.extend(["--memory", docker_cfg.memory_limit])

        # Bind-mount project directory at the same path
        argv.extend(["-v", f"{cwd_str}:{cwd_str}"])
        argv.extend(["-w", cwd_str])

        # Extra mounts
        for mount in docker_cfg.extra_mounts:
            argv.extend(["-v", mount])

        # Extra environment variables
        for key, value in docker_cfg.extra_env.items():
            argv.extend(["-e", f"{key}={value}"])

        argv.extend([docker_cfg.image, "tail", "-f", "/dev/null"])
        return argv

    async def start(self) -> None:
        """Create and start the sandbox container.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_build_run_argv``, ``logger.info``, ``ensure_image_available``.

        Event loop: This coroutine awaits subprocess work; preserve process cleanup and avoid
        shell-blocking operations.

        Change safety: Preserve argv boundaries, timeouts, and child cleanup; preserve exception
        and fallback behavior expected by callers.
        """
        from openharness.sandbox.docker_image import ensure_image_available

        docker_cfg = self.settings.sandbox.docker
        available = await ensure_image_available(
            docker_cfg.image, docker_cfg.auto_build_image
        )
        if not available:
            raise SandboxUnavailableError(
                f"Docker image {docker_cfg.image!r} is not available and "
                "auto_build_image is disabled"
            )

        argv = self._build_run_argv()
        logger.info("Starting Docker sandbox: %s", " ".join(argv))

        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            msg = stderr.decode("utf-8", errors="replace").strip()
            raise SandboxUnavailableError(f"Failed to start Docker sandbox: {msg}")

        self._running = True
        logger.info("Docker sandbox started: %s", self._container_name)

    async def stop(self) -> None:
        """Stop and remove the sandbox container.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``shutil.which``, ``logger.info``, ``asyncio.create_subprocess_exec``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve argv boundaries, timeouts, and child cleanup; preserve exception
        and fallback behavior expected by callers.
        """
        if not self._running:
            return
        docker = shutil.which("docker") or "docker"
        try:
            process = await asyncio.create_subprocess_exec(
                docker,
                "stop",
                "-t",
                "5",
                self._container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=15)
        except (asyncio.TimeoutError, OSError) as exc:
            logger.warning("Error stopping Docker sandbox: %s", exc)
        finally:
            self._running = False
            logger.info("Docker sandbox stopped: %s", self._container_name)

    def stop_sync(self) -> None:
        """Synchronous stop for use in atexit handlers.

        Integration: Called by ``TestContainerLifecycle.test_stop_sync`` and collaborates with
        ``shutil.which``, ``subprocess.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve argv boundaries, timeouts, and child cleanup; preserve exception
        and fallback behavior expected by callers.
        """
        if not self._running:
            return
        docker = shutil.which("docker") or "docker"
        try:
            subprocess.run(
                [docker, "stop", "-t", "3", self._container_name],
                capture_output=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass
        finally:
            self._running = False

    async def exec_command(
        self,
        argv: list[str],
        *,
        cwd: str | Path,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
        env: dict[str, str] | None = None,
    ) -> asyncio.subprocess.Process:
        """Execute a command inside the sandbox container.

        Returns an ``asyncio.subprocess.Process`` with the same interface as
        ``asyncio.create_subprocess_exec``.

        Integration: Called by ``_run_and_capture``,
        ``TestCommandExecution.test_env_vars_passed`` and collaborates with ``cmd.extend``,
        ``cmd.append``, ``SandboxUnavailableError``.

        Event loop: This coroutine awaits subprocess work; preserve process cleanup and avoid
        shell-blocking operations.

        Change safety: Preserve argv boundaries, timeouts, and child cleanup; preserve exception
        and fallback behavior expected by callers.
        """
        if not self._running:
            raise SandboxUnavailableError("Docker sandbox session is not running")

        docker = shutil.which("docker") or "docker"
        cmd: list[str] = [docker, "exec"]
        cmd.extend(["-w", str(Path(cwd).resolve())])

        if env:
            for key, value in env.items():
                cmd.extend(["-e", f"{key}={value}"])

        cmd.append(self._container_name)
        cmd.extend(argv)

        return await asyncio.create_subprocess_exec(
            *cmd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )
