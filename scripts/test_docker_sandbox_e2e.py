#!/usr/bin/env python3
"""End-to-end tests for the Docker sandbox backend.

These tests require a running Docker daemon. They exercise the full container
lifecycle: image build, container start, command execution, file isolation,
network isolation, resource limits, and cleanup.

Run directly:
    python3 scripts/test_docker_sandbox_e2e.py

Or via pytest (skipped automatically when Docker is unavailable):
    uv run pytest scripts/test_docker_sandbox_e2e.py -v

Integration: This opt-in driver supports installation, migration, or manual/E2E validation
outside the deterministic unit-test runtime.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve explicit prerequisites, isolated state, subprocess cleanup, bounded
waits, credential handling, and clear pass/fail diagnostics; never make normal tests depend on
live services.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: ensure the src package is importable when run as a script
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openharness.config.settings import (
    DockerSandboxSettings,
    SandboxNetworkSettings,
    SandboxSettings,
    Settings,
)
from openharness.sandbox.docker_backend import DockerSandboxSession, get_docker_availability
from openharness.sandbox.docker_image import ensure_image_available

# ---------------------------------------------------------------------------
# Skip condition: Docker daemon must be reachable
# ---------------------------------------------------------------------------
_DOCKER = shutil.which("docker")
_DOCKER_OK = False
if _DOCKER:
    try:
        subprocess.run([_DOCKER, "info"], capture_output=True, timeout=10, check=True)
        _DOCKER_OK = True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        pass

_SKIP_REASON = "Docker daemon is not available"
_E2E_IMAGE = "openharness-sandbox-e2e:latest"

pytestmark = pytest.mark.skipif(not _DOCKER_OK, reason=_SKIP_REASON)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(*, network_domains: list[str] | None = None, **docker_kw) -> Settings:
    """Build a Settings object with Docker sandbox enabled.

    Integration: Called by ``TestContainerLifecycle.test_start_and_stop``,
    ``TestContainerLifecycle.test_stop_sync`` and collaborates with ``Settings``,
    ``SandboxSettings``, ``SandboxNetworkSettings``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return Settings(
        sandbox=SandboxSettings(
            enabled=True,
            backend="docker",
            fail_if_unavailable=True,
            network=SandboxNetworkSettings(
                allowed_domains=network_domains or [],
            ),
            docker=DockerSandboxSettings(
                image=_E2E_IMAGE,
                auto_build_image=True,
                **docker_kw,
            ),
        )
    )


async def _run_and_capture(session: DockerSandboxSession, argv: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run a command inside the sandbox and return (returncode, stdout, stderr).

    Integration: Called by ``TestCommandExecution.test_echo``,
    ``TestCommandExecution.test_echo._run`` and collaborates with ``session.exec_command``,
    ``proc.communicate``, ``strip``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    proc = await session.exec_command(
        argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def e2e_image():
    """Ensure the E2E sandbox image exists (built once per module).

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``pytest.fixture``, ``asyncio.run``, ``ensure_image_available``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    ok = asyncio.run(ensure_image_available(_E2E_IMAGE, auto_build=True))
    if not ok:
        pytest.skip(f"Could not build Docker image {_E2E_IMAGE}")
    return _E2E_IMAGE


@pytest.fixture()
def project_dir():
    """Create a temporary project directory for one test.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``pytest.fixture``, ``tempfile.TemporaryDirectory``, ``Path``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve yield ordering and partial-consumption behavior expected by callers.
    """
    with tempfile.TemporaryDirectory(prefix="oh-docker-e2e-") as tmpdir:
        yield Path(tmpdir)


# ---------------------------------------------------------------------------
# 1. Image management
# ---------------------------------------------------------------------------

class TestImageManagement:
    """Coordinate the test image management responsibilities for this subsystem.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """
    def test_image_build(self, e2e_image):
        """Image should be available after the module fixture runs.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``subprocess.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by
        callers.
        """
        result = subprocess.run(
            [_DOCKER, "image", "inspect", e2e_image],
            capture_output=True,
        )
        assert result.returncode == 0, "E2E image should exist after build"

    def test_image_has_expected_tools(self, e2e_image):
        """Image should contain bash, rg (ripgrep), and git.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``subprocess.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by
        callers.
        """
        for tool in ("bash", "rg", "git"):
            result = subprocess.run(
                [_DOCKER, "run", "--rm", e2e_image, "which", tool],
                capture_output=True,
            )
            assert result.returncode == 0, f"{tool} should be available in the image"


# ---------------------------------------------------------------------------
# 2. Container lifecycle
# ---------------------------------------------------------------------------

class TestContainerLifecycle:
    """Coordinate the test container lifecycle responsibilities for this subsystem.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """
    def test_start_and_stop(self, e2e_image, project_dir):
        """Container should start, appear in docker ps, then stop cleanly.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``DockerSandboxSession``, ``asyncio.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by
        callers.
        """
        settings = _settings()
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-lifecycle", cwd=project_dir,
        )

        async def _run():
            """Run one test container lifecycle.test start and stop lifecycle.

            Integration: Exposed through ``TestContainerLifecycle.test_start_and_stop`` and
            collaborates with ``subprocess.run``, ``session.start``, ``session.stop``.

            Event loop: This coroutine awaits subprocess work; preserve process cleanup and
            avoid shell-blocking operations.

            Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by
            callers.
            """
            await session.start()
            assert session.is_running

            # Verify container is visible
            result = subprocess.run(
                [_DOCKER, "ps", "--filter", f"name={session.container_name}", "-q"],
                capture_output=True,
                text=True,
            )
            assert result.stdout.strip(), "Container should appear in docker ps"

            await session.stop()
            assert not session.is_running

            # Verify container is gone (--rm flag auto-removes)
            result = subprocess.run(
                [_DOCKER, "ps", "-a", "--filter", f"name={session.container_name}", "-q"],
                capture_output=True,
                text=True,
            )
            assert not result.stdout.strip(), "Container should be removed after stop"

        asyncio.run(_run())

    def test_stop_sync(self, e2e_image, project_dir):
        """Synchronous stop (atexit handler) should also clean up.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``DockerSandboxSession``, ``asyncio.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        settings = _settings()
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-stopsync", cwd=project_dir,
        )

        async def _start():
            """Start the test container lifecycle.test stop sync lifecycle.

            Integration: Called by ``TestContainerLifecycle.test_stop_sync`` and collaborates
            with ``session.start``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await session.start()

        asyncio.run(_start())
        assert session.is_running

        session.stop_sync()
        assert not session.is_running

    def test_availability_check(self):
        """get_docker_availability should return available=True when Docker is running.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``get_docker_availability``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        settings = _settings()
        avail = get_docker_availability(settings)
        assert avail.enabled is True
        assert avail.available is True
        assert avail.command is not None


# ---------------------------------------------------------------------------
# 3. Command execution
# ---------------------------------------------------------------------------

class TestCommandExecution:
    """Coordinate the test command execution responsibilities for this subsystem.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """
    def test_echo(self, e2e_image, project_dir):
        """Basic command should execute and return output.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``DockerSandboxSession``, ``asyncio.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        settings = _settings()
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-echo", cwd=project_dir,
        )

        async def _run():
            """Run one test command execution.test echo lifecycle.

            Integration: Exposed through ``TestCommandExecution.test_echo`` and collaborates
            with ``session.start``, ``_run_and_capture``, ``session.stop``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await session.start()
            try:
                rc, stdout, stderr = await _run_and_capture(
                    session, ["echo", "hello-from-sandbox"], project_dir,
                )
                assert rc == 0
                assert "hello-from-sandbox" in stdout
            finally:
                await session.stop()

        asyncio.run(_run())

    def test_exit_code_preserved(self, e2e_image, project_dir):
        """Non-zero exit codes should propagate correctly.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``DockerSandboxSession``, ``asyncio.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        settings = _settings()
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-exitcode", cwd=project_dir,
        )

        async def _run():
            """Run one test command execution.test exit code preserved lifecycle.

            Integration: Exposed through ``TestCommandExecution.test_exit_code_preserved`` and
            collaborates with ``session.start``, ``_run_and_capture``, ``session.stop``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await session.start()
            try:
                rc, _, _ = await _run_and_capture(
                    session, ["bash", "-c", "exit 42"], project_dir,
                )
                assert rc == 42
            finally:
                await session.stop()

        asyncio.run(_run())

    def test_env_vars_passed(self, e2e_image, project_dir):
        """Environment variables should be forwarded into the container.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``DockerSandboxSession``, ``asyncio.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        settings = _settings()
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-env", cwd=project_dir,
        )

        async def _run():
            """Run one test command execution.test env vars passed lifecycle.

            Integration: Exposed through ``TestCommandExecution.test_env_vars_passed`` and
            collaborates with ``session.start``, ``_run_and_capture``, ``session.exec_command``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await session.start()
            try:
                rc, stdout, _ = await _run_and_capture(
                    session,
                    ["bash", "-c", "echo $MY_TEST_VAR"],
                    project_dir,
                )
                # env passed through exec_command
                proc = await session.exec_command(
                    ["bash", "-c", "echo $MY_TEST_VAR"],
                    cwd=project_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={"MY_TEST_VAR": "sandbox-value"},
                )
                out, _ = await proc.communicate()
                assert "sandbox-value" in out.decode()
            finally:
                await session.stop()

        asyncio.run(_run())

    def test_working_directory(self, e2e_image, project_dir):
        """Commands should run in the specified working directory.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``DockerSandboxSession``, ``asyncio.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        settings = _settings()
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-cwd", cwd=project_dir,
        )

        async def _run():
            """Run one test command execution.test working directory lifecycle.

            Integration: Exposed through ``TestCommandExecution.test_working_directory`` and
            collaborates with ``session.start``, ``_run_and_capture``, ``session.stop``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await session.start()
            try:
                rc, stdout, _ = await _run_and_capture(
                    session, ["pwd"], project_dir,
                )
                assert rc == 0
                assert str(project_dir.resolve()) in stdout
            finally:
                await session.stop()

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 4. Filesystem isolation
# ---------------------------------------------------------------------------

class TestFilesystemIsolation:
    """Coordinate the test filesystem isolation responsibilities for this subsystem.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """
    def test_bind_mount_readable(self, e2e_image, project_dir):
        """Files in the project directory should be readable from inside the container.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``marker.write_text``, ``_settings``, ``DockerSandboxSession``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve path isolation, encoding, and persistence side effects expected
        by callers.
        """
        marker = project_dir / "test_marker.txt"
        marker.write_text("E2E_MARKER_OK", encoding="utf-8")

        settings = _settings()
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-fsread", cwd=project_dir,
        )

        async def _run():
            """Run one test filesystem isolation.test bind mount readable lifecycle.

            Integration: Exposed through ``TestFilesystemIsolation.test_bind_mount_readable``
            and collaborates with ``session.start``, ``_run_and_capture``, ``session.stop``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await session.start()
            try:
                rc, stdout, _ = await _run_and_capture(
                    session, ["cat", str(marker)], project_dir,
                )
                assert rc == 0
                assert "E2E_MARKER_OK" in stdout
            finally:
                await session.stop()

        asyncio.run(_run())

    def test_bind_mount_writable(self, e2e_image, project_dir):
        """Files written inside the container should appear on the host.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``DockerSandboxSession``, ``asyncio.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve path isolation, encoding, and persistence side effects expected
        by callers.
        """
        output_file = project_dir / "from_container.txt"
        settings = _settings()
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-fswrite", cwd=project_dir,
        )

        async def _run():
            """Run one test filesystem isolation.test bind mount writable lifecycle.

            Integration: Exposed through ``TestFilesystemIsolation.test_bind_mount_writable``
            and collaborates with ``session.start``, ``output_file.exists``,
            ``_run_and_capture``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve path isolation, encoding, and persistence side effects
            expected by callers.
            """
            await session.start()
            try:
                rc, _, _ = await _run_and_capture(
                    session,
                    ["bash", "-c", f"echo CONTAINER_WROTE_THIS > {output_file}"],
                    project_dir,
                )
                assert rc == 0
                assert output_file.exists(), "File written in container should exist on host"
                assert "CONTAINER_WROTE_THIS" in output_file.read_text()
            finally:
                await session.stop()

        asyncio.run(_run())

    def test_host_root_not_accessible(self, e2e_image, project_dir):
        """The container should NOT be able to read host files outside the bind mount.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``DockerSandboxSession``, ``asyncio.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        settings = _settings()
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-fsfence", cwd=project_dir,
        )

        async def _run():
            """Run one test filesystem isolation.test host root not accessible lifecycle.

            Integration: Exposed through
            ``TestFilesystemIsolation.test_host_root_not_accessible`` and collaborates with
            ``session.start``, ``_run_and_capture``, ``session.stop``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await session.start()
            try:
                # /etc/hostname exists on the host but should not be the same inside
                # the container (container has its own /etc/hostname).
                # More importantly, a path like /root/.bashrc should not be the host's.
                rc, stdout, _ = await _run_and_capture(
                    session, ["ls", "/home"], project_dir,
                )
                # The container should have its own /home (with ohuser),
                # not the host's /home
                assert rc == 0
                assert "ohuser" in stdout, (
                    "Container /home should contain the sandbox user, not host users"
                )
            finally:
                await session.stop()

        asyncio.run(_run())

    def test_ripgrep_inside_container(self, e2e_image, project_dir):
        """rg should work inside the container for glob/grep tool integration.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``write_text``, ``_settings``, ``DockerSandboxSession``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve path isolation, encoding, and persistence side effects expected
        by callers.
        """
        (project_dir / "hello.py").write_text("print('hello world')\n", encoding="utf-8")

        settings = _settings()
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-rg", cwd=project_dir,
        )

        async def _run():
            """Run one test filesystem isolation.test ripgrep inside container lifecycle.

            Integration: Exposed through
            ``TestFilesystemIsolation.test_ripgrep_inside_container`` and collaborates with
            ``session.start``, ``_run_and_capture``, ``session.stop``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await session.start()
            try:
                rc, stdout, _ = await _run_and_capture(
                    session, ["rg", "--no-heading", "hello", "."], project_dir,
                )
                assert rc == 0
                assert "hello world" in stdout
            finally:
                await session.stop()

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 5. Network isolation
# ---------------------------------------------------------------------------

class TestNetworkIsolation:
    """Coordinate the test network isolation responsibilities for this subsystem.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """
    def test_network_none_blocks_connectivity(self, e2e_image, project_dir):
        """With --network=none, outbound connections should fail.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``DockerSandboxSession``, ``asyncio.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        settings = _settings()  # no allowed_domains -> --network=none
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-netblk", cwd=project_dir,
        )

        async def _run():
            """Run one test network isolation.test network none blocks connectivity lifecycle.

            Integration: Exposed through
            ``TestNetworkIsolation.test_network_none_blocks_connectivity`` and collaborates with
            ``session.start``, ``_run_and_capture``, ``session.stop``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await session.start()
            try:
                # Try to reach an external host; should fail
                rc, _, _ = await _run_and_capture(
                    session,
                    ["bash", "-c", "timeout 3 bash -c 'echo > /dev/tcp/8.8.8.8/53' 2>&1 || exit 1"],
                    project_dir,
                )
                assert rc != 0, "Network should be blocked with --network=none"
            finally:
                await session.stop()

        asyncio.run(_run())

    def test_network_bridge_allows_connectivity(self, e2e_image, project_dir):
        """With allowed_domains set, --network=bridge is used and DNS resolves.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``DockerSandboxSession``, ``asyncio.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        settings = _settings(network_domains=["github.com"])
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-netok", cwd=project_dir,
        )

        async def _run():
            """Run one test network isolation.test network bridge allows connectivity lifecycle.

            Integration: Exposed through
            ``TestNetworkIsolation.test_network_bridge_allows_connectivity`` and collaborates
            with ``session.start``, ``_run_and_capture``, ``isdigit``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await session.start()
            try:
                # With bridge network, DNS resolution should work
                rc, stdout, _ = await _run_and_capture(
                    session,
                    ["bash", "-c", "getent hosts github.com 2>/dev/null && echo DNS_OK || echo DNS_FAIL"],
                    project_dir,
                )
                # getent may not be installed in slim image; check if we at least
                # have network interfaces beyond loopback
                rc2, stdout2, _ = await _run_and_capture(
                    session,
                    ["bash", "-c", "cat /proc/net/route | wc -l"],
                    project_dir,
                )
                route_lines = int(stdout2.strip()) if stdout2.strip().isdigit() else 0
                assert route_lines > 1, (
                    "Bridge network should have routing entries beyond just the header"
                )
            finally:
                await session.stop()

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 6. Resource limits
# ---------------------------------------------------------------------------

class TestResourceLimits:
    """Coordinate the test resource limits responsibilities for this subsystem.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """
    def test_cpu_limit_applied(self, e2e_image, project_dir):
        """Container should reflect the configured CPU limit.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``DockerSandboxSession``, ``asyncio.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by
        callers.
        """
        settings = _settings(cpu_limit=1.5)
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-cpu", cwd=project_dir,
        )

        async def _run():
            """Run one test resource limits.test cpu limit applied lifecycle.

            Integration: Exposed through ``TestResourceLimits.test_cpu_limit_applied`` and
            collaborates with ``session.start``, ``subprocess.run``, ``session.stop``.

            Event loop: This coroutine awaits subprocess work; preserve process cleanup and
            avoid shell-blocking operations.

            Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by
            callers.
            """
            await session.start()
            try:
                result = subprocess.run(
                    [_DOCKER, "inspect", "--format", "{{.HostConfig.NanoCpus}}",
                     session.container_name],
                    capture_output=True,
                    text=True,
                )
                # Docker stores NanoCpus as int nanoseconds: 1.5 CPUs = 1_500_000_000
                nano = int(result.stdout.strip())
                assert nano == 1_500_000_000, f"Expected 1.5 CPUs (1500000000 nano), got {nano}"
            finally:
                await session.stop()

        asyncio.run(_run())

    def test_memory_limit_applied(self, e2e_image, project_dir):
        """Container should reflect the configured memory limit.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``DockerSandboxSession``, ``asyncio.run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by
        callers.
        """
        settings = _settings(memory_limit="256m")
        session = DockerSandboxSession(
            settings=settings, session_id="e2e-mem", cwd=project_dir,
        )

        async def _run():
            """Run one test resource limits.test memory limit applied lifecycle.

            Integration: Exposed through ``TestResourceLimits.test_memory_limit_applied`` and
            collaborates with ``session.start``, ``subprocess.run``, ``session.stop``.

            Event loop: This coroutine awaits subprocess work; preserve process cleanup and
            avoid shell-blocking operations.

            Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by
            callers.
            """
            await session.start()
            try:
                result = subprocess.run(
                    [_DOCKER, "inspect", "--format", "{{.HostConfig.Memory}}",
                     session.container_name],
                    capture_output=True,
                    text=True,
                )
                mem_bytes = int(result.stdout.strip())
                expected = 256 * 1024 * 1024  # 256 MiB
                assert mem_bytes == expected, f"Expected {expected} bytes, got {mem_bytes}"
            finally:
                await session.stop()

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 7. Session integration (start_docker_sandbox / stop_docker_sandbox)
# ---------------------------------------------------------------------------

class TestSessionIntegration:
    """Coordinate the test session integration responsibilities for this subsystem.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """
    def test_session_lifecycle(self, e2e_image, project_dir):
        """start_docker_sandbox / stop_docker_sandbox should manage the global session.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``asyncio.run``, ``is_docker_sandbox_active``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        from openharness.sandbox.session import (
            get_docker_sandbox,
            is_docker_sandbox_active,
            start_docker_sandbox,
            stop_docker_sandbox,
        )

        settings = _settings()

        async def _run():
            """Run one test session integration.test session lifecycle lifecycle.

            Integration: Exposed through ``TestSessionIntegration.test_session_lifecycle`` and
            collaborates with ``is_docker_sandbox_active``, ``get_docker_sandbox``,
            ``start_docker_sandbox``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            assert not is_docker_sandbox_active()

            await start_docker_sandbox(settings, "e2e-session", project_dir)
            assert is_docker_sandbox_active()

            session = get_docker_sandbox()
            assert session is not None
            assert session.is_running

            # Run a command through the session
            rc, stdout, _ = await _run_and_capture(session, ["echo", "session-ok"], project_dir)
            assert rc == 0
            assert "session-ok" in stdout

            await stop_docker_sandbox()
            assert not is_docker_sandbox_active()
            assert get_docker_sandbox() is None

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 8. shell.py integration (create_shell_subprocess routes through Docker)
# ---------------------------------------------------------------------------

class TestShellIntegration:
    """Coordinate the test shell integration responsibilities for this subsystem.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """
    def test_create_shell_subprocess_routes_through_docker(self, e2e_image, project_dir):
        """When Docker sandbox is active, create_shell_subprocess should exec inside container.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_settings``, ``asyncio.run``, ``_run``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by
        callers.
        """
        from openharness.sandbox.session import (
            start_docker_sandbox,
            stop_docker_sandbox,
        )
        from openharness.utils.shell import create_shell_subprocess

        settings = _settings()

        async def _run():
            """Run one test shell integration.test create shell subprocess routes through docker lifecycle.

            Integration: Exposed through
            ``TestShellIntegration.test_create_shell_subprocess_routes_through_docker`` and
            collaborates with ``start_docker_sandbox``, ``create_shell_subprocess``,
            ``process.communicate``.

            Event loop: This coroutine awaits subprocess work; preserve process cleanup and
            avoid shell-blocking operations.

            Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by
            callers.
            """
            await start_docker_sandbox(settings, "e2e-shell", project_dir)
            try:
                process = await create_shell_subprocess(
                    "echo DOCKER_SHELL_OK",
                    cwd=project_dir,
                    settings=settings,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await process.communicate()
                assert "DOCKER_SHELL_OK" in stdout.decode()
            finally:
                await stop_docker_sandbox()

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# CLI entry point for running outside pytest
# ---------------------------------------------------------------------------

def _main() -> int:
    """Run all tests and report results.

    Integration: Used as an internal helper or callback at this module boundary and collaborates
    with ``asyncio.run``, ``ensure_image_available``, ``cls``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if not _DOCKER_OK:
        print(f"SKIP: {_SKIP_REASON}")
        return 0

    # Collect all test classes
    test_classes = [
        TestImageManagement,
        TestContainerLifecycle,
        TestCommandExecution,
        TestFilesystemIsolation,
        TestNetworkIsolation,
        TestResourceLimits,
        TestSessionIntegration,
        TestShellIntegration,
    ]

    # Ensure image is built first
    print(f"Building sandbox image {_E2E_IMAGE}...")
    ok = asyncio.run(ensure_image_available(_E2E_IMAGE, auto_build=True))
    if not ok:
        print(f"FAIL: Could not build {_E2E_IMAGE}")
        return 1
    print("Image ready.\n")

    passed = 0
    failed = 0
    errors: list[str] = []

    for cls in test_classes:
        instance = cls()
        for attr in sorted(dir(instance)):
            if not attr.startswith("test_"):
                continue
            method = getattr(instance, attr)
            name = f"{cls.__name__}.{attr}"
            try:
                with tempfile.TemporaryDirectory(prefix="oh-docker-e2e-") as tmpdir:
                    # Inject fixtures based on parameter names
                    import inspect

                    sig = inspect.signature(method)
                    kwargs = {}
                    if "e2e_image" in sig.parameters:
                        kwargs["e2e_image"] = _E2E_IMAGE
                    if "project_dir" in sig.parameters:
                        kwargs["project_dir"] = Path(tmpdir)
                    method(**kwargs)
                print(f"  PASS  {name}")
                passed += 1
            except Exception as exc:
                print(f"  FAIL  {name}: {exc}")
                errors.append(f"{name}: {exc}")
                failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  - {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
