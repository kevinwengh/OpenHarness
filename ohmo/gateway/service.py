"""Gateway service lifecycle for ohmo.

Integration: This ohmo module specializes the reusable OpenHarness runtime with personal
workspace, memory, session, gateway, or channel behavior; core modules must not depend on it.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve the ohmo workspace boundary, conversation/session isolation, attachment
and channel contracts, credential redaction, and cleanup of per-session runtimes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import os.path
import signal
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    import ctypes

from openharness.channels.bus.events import OutboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.channels.impl.manager import ChannelManager

from ohmo.automation.service import OhmoAutomationService
from ohmo.gateway.bridge import OhmoGatewayBridge
from ohmo.gateway.config import build_channel_manager_config, load_gateway_config
from ohmo.gateway.models import GatewayState
from ohmo.gateway.runtime import OhmoSessionRuntimePool
from ohmo.workspace import (
    get_gateway_restart_notice_path,
    get_logs_dir,
    get_state_path,
    get_workspace_root,
    initialize_workspace,
)

logger = logging.getLogger(__name__)
_REPO_ROOT = Path(__file__).resolve().parents[2]


class OhmoGatewayService:
    """Foreground/background service wrapper for the personal gateway.

    Integration: Constructed or referenced by ``gateway_run_cmd``, ``start_gateway_process``.

    Event loop: Async methods ``request_restart``, ``create_group``, ``create_group_for_user``,
    ``publish_group_welcome`` run on their caller's loop; instances must retain clear task,
    cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self, cwd: str | Path | None = None, workspace: str | Path | None = None) -> None:
        """Initialize ``OhmoGatewayService`` and bind its runtime dependencies.

        Integration: Exposed through ``OhmoGatewayService`` and collaborates with ``os.chdir``,
        ``initialize_workspace``, ``load_gateway_config``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._cwd = str(Path(cwd or Path.cwd()).resolve())
        self._workspace = workspace
        os.chdir(self._cwd)
        root = initialize_workspace(self._workspace)
        os.environ["OHMO_WORKSPACE"] = str(root)
        self._config = load_gateway_config(self._workspace)
        if self._config.allow_remote_admin_commands and self._config.allowed_remote_admin_commands:
            logger.warning(
                "ohmo gateway remote administrative commands enabled commands=%s",
                ",".join(self._config.allowed_remote_admin_commands),
            )
        self._bus = MessageBus()
        self._manager = ChannelManager(build_channel_manager_config(self._config), self._bus)
        self._runtime_pool = OhmoSessionRuntimePool(
            cwd=self._cwd,
            workspace=self._workspace,
            provider_profile=self._config.provider_profile,
            create_feishu_group=self.create_group_for_user,
            publish_group_welcome=self.publish_group_welcome,
        )
        self._automation_service = OhmoAutomationService(
            workspace=root,
            cwd=self._cwd,
            bus=self._bus,
            provider_profile=self._config.provider_profile,
        )
        self._stop_event: asyncio.Event | None = None
        self._restart_requested = False
        self._bridge = OhmoGatewayBridge(
            bus=self._bus,
            runtime_pool=self._runtime_pool,
            restart_gateway=self.request_restart,
            workspace=root,
            feishu_group_policy=str(
                self._config.channel_configs.get("feishu", {}).get("group_policy", "managed_or_mention")
            ),
            automation_service=self._automation_service,
        )

    @property
    def pid_file(self) -> Path:
        """Derive pid file from the current inputs and subsystem state.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``get_workspace_root``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return get_workspace_root(self._workspace) / "gateway.pid"

    @property
    def log_file(self) -> Path:
        """Derive log file from the current inputs and subsystem state.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``get_logs_dir``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return get_logs_dir(self._workspace) / "gateway.log"

    @property
    def state_file(self) -> Path:
        """Derive state file from the current inputs and subsystem state.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``get_state_path``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return get_state_path(self._workspace)

    def _channel_last_error(self) -> str | None:
        """Derive channel last error from the current inputs and subsystem state.

        Integration: Called by ``OhmoGatewayService.write_state`` and collaborates with
        ``_manager.channels.items``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        for name, channel in self._manager.channels.items():
            error = getattr(channel, "last_error", None)
            if error:
                return f"{name}: {error}"
        return None

    def write_state(self, *, running: bool, last_error: str | None = None) -> None:
        """Write state for the enclosing subsystem.

        Integration: Called by ``OhmoGatewayService.run_foreground``,
        ``OhmoGatewayService.run_foreground._state_heartbeat`` and collaborates with
        ``GatewayState``, ``state_file.write_text``, ``state.model_dump_json``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve path isolation, encoding, and persistence side effects expected
        by callers.
        """
        automation = self._automation_service.status_counts()
        state = GatewayState(
            running=running,
            pid=os.getpid() if running else None,
            active_sessions=self._runtime_pool.active_sessions,
            provider_profile=self._config.provider_profile,
            enabled_channels=self._config.enabled_channels,
            automation_loaded=automation["loaded"],
            automation_invalid=automation["invalid"],
            automation_active=automation["active"],
            automation_waiting=automation["waiting"],
            automation_failed=automation["failed"],
            last_error=last_error or self._channel_last_error(),
        )
        self.state_file.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")

    async def request_restart(self, message, session_key: str) -> None:
        """Ask the foreground gateway loop to restart itself.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``write_text``, ``asyncio.sleep``, ``get_gateway_restart_notice_path``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve path isolation, encoding, and persistence side effects expected
        by callers.
        """
        restart_notice = {
            "channel": message.channel,
            "chat_id": message.chat_id,
            "session_key": session_key,
            "content": "✅ gateway 已经重新连上，可以继续了。\nGateway is back online. We can continue.",
        }
        get_gateway_restart_notice_path(self._workspace).write_text(
            json.dumps(restart_notice, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._restart_requested = True
        # Let the outbound dispatcher flush the restart notice to the IM channel
        # before we tear down the bridge and channel connections.
        await asyncio.sleep(0.75)
        if self._stop_event is not None:
            self._stop_event.set()

    async def create_group(self, message, name: str) -> str:
        """Create a managed group through the active channel implementation.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``RuntimeError``, ``create_group_for_user``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        if message.channel != "feishu":
            raise RuntimeError(f"{message.channel} does not support managed group creation.")
        return await self.create_group_for_user(str(message.sender_id), name)

    async def create_group_for_user(self, user_open_id: str, name: str) -> str:
        """Create a managed Feishu group for a user open_id.

        Integration: Called by ``OhmoGatewayService.create_group`` and collaborates with
        ``_manager.get_channel``, ``creator``, ``RuntimeError``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        channel = self._manager.get_channel("feishu")
        if channel is None:
            raise RuntimeError("Feishu channel is not enabled.")
        creator = getattr(channel, "create_managed_group", None)
        if creator is None:
            raise RuntimeError("Feishu channel does not support managed group creation.")
        result = creator(user_open_id=str(user_open_id), name=name)
        return str(await result if asyncio.iscoroutine(result) else result)

    async def publish_group_welcome(self, chat_id: str, content: str, owner_open_id: str) -> None:
        """Send a welcome message to a newly created managed group.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_bus.publish_outbound``, ``OutboundMessage``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        await self._bus.publish_outbound(
            OutboundMessage(
                channel="feishu",
                chat_id=chat_id,
                content=content,
                metadata={"chat_type": "group", "_session_key": f"feishu:{chat_id}:{owner_open_id}"},
            )
        )

    def _exec_restart(self) -> None:
        """Apply exec restart to the enclosing subsystem state.

        Integration: Called by ``OhmoGatewayService.run_foreground`` and collaborates with
        ``logger.info``, ``os.execv``, ``get_workspace_root``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        root = str(get_workspace_root(self._workspace))
        argv = [
            sys.executable,
            "-m",
            "ohmo",
            "gateway",
            "run",
            "--cwd",
            self._cwd,
            "--workspace",
            root,
        ]
        logger.info("ohmo gateway restarting in-place argv=%s", argv)
        os.execv(sys.executable, argv)

    async def _publish_pending_restart_notice(self) -> None:
        """Publish pending restart notice for the enclosing subsystem.

        Integration: Called by ``OhmoGatewayService.run_foreground`` and collaborates with
        ``get_gateway_restart_notice_path``, ``path.exists``, ``json.loads``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve path isolation, encoding, and persistence side effects expected
        by callers.
        """
        path = get_gateway_restart_notice_path(self._workspace)
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            channel = payload.get("channel")
            chat_id = payload.get("chat_id")
            content = payload.get("content")
            session_key = payload.get("session_key")
            if not isinstance(channel, str) or not isinstance(chat_id, str) or not isinstance(content, str):
                return
            await asyncio.sleep(2.0)
            await self._bus.publish_outbound(
                OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=content,
                    metadata={"_session_key": session_key} if isinstance(session_key, str) else {},
                )
            )
            logger.info(
                "ohmo gateway published restart confirmation channel=%s chat_id=%s session_key=%s",
                channel,
                chat_id,
                session_key,
            )
        finally:
            path.unlink(missing_ok=True)

    async def run_foreground(self) -> int:
        """Run foreground for the enclosing subsystem.

        Integration: Called by ``gateway_run_cmd`` and collaborates with
        ``pid_file.write_text``, ``write_state``, ``asyncio.create_task``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
        exception and fallback behavior expected by callers.
        """
        self.pid_file.write_text(str(os.getpid()), encoding="utf-8")
        self.write_state(running=True)
        await self._automation_service.start()
        bridge_task = asyncio.create_task(self._bridge.run(), name="ohmo-gateway-bridge")
        manager_task = asyncio.create_task(self._manager.start_all(), name="ohmo-gateway-channels")
        restart_notice_task = asyncio.create_task(
            self._publish_pending_restart_notice(),
            name="ohmo-gateway-restart-notice",
        )
        stop_event = asyncio.Event()
        self._stop_event = stop_event
        self._restart_requested = False

        def _stop(*_: object) -> None:
            """Stop the active ohmo gateway service.run foreground lifecycle.

            Integration: Used as an internal helper or callback at this module boundary.

            Concurrency: This is synchronous; preserve deterministic behavior for its direct
            callers.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, _stop)

        async def _state_heartbeat() -> None:
            """Run the state heartbeat workflow through its asynchronous collaborators.

            Integration: Called by ``OhmoGatewayService.run_foreground`` and collaborates with
            ``stop_event.is_set``, ``write_state``, ``asyncio.sleep``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            while not stop_event.is_set():
                self.write_state(running=True)
                await asyncio.sleep(5.0)

        state_task = asyncio.create_task(_state_heartbeat(), name="ohmo-gateway-state")

        try:
            await stop_event.wait()
        except Exception as exc:
            self.write_state(running=False, last_error=str(exc))
            raise
        finally:
            self._bridge.stop()
            bridge_task.cancel()
            manager_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await bridge_task
            with contextlib.suppress(asyncio.CancelledError):
                await manager_task
            await self._automation_service.stop()
            if not state_task.done():
                state_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await state_task
            if not restart_notice_task.done():
                restart_notice_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await restart_notice_task
            await self._manager.stop_all()
            self.write_state(running=False)
            self.pid_file.unlink(missing_ok=True)
            self._stop_event = None
        if self._restart_requested:
            self._exec_restart()
        return 0


def start_gateway_process(cwd: str | Path | None = None, workspace: str | Path | None = None) -> int:
    """Start the gateway as a detached subprocess.

    Integration: Called by ``_maybe_restart_gateway``, ``gateway_start_cmd`` and collaborates
    with ``OhmoGatewayService``, ``service.log_file.parent.mkdir``, ``os.environ.copy``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    argv boundaries, timeouts, and child cleanup expected by callers.
    """
    service = OhmoGatewayService(cwd, workspace)
    service.log_file.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    pythonpath_entries = [str(_REPO_ROOT)]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_entries.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

    popen_kwargs: dict = {
        "cwd": service._cwd,
        "stdout": None,
        "stderr": None,
        "env": env,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        popen_kwargs["stdin"] = subprocess.DEVNULL
    else:
        popen_kwargs["start_new_session"] = True

    with service.log_file.open("a", encoding="utf-8") as log_file:
        popen_kwargs["stdout"] = log_file
        popen_kwargs["stderr"] = log_file
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "ohmo",
                "gateway",
                "run",
                "--cwd",
                service._cwd,
                "--workspace",
                str(get_workspace_root(workspace)),
                "--no-console-log",
            ],
            **popen_kwargs,
        )
    return process.pid


def _pid_is_running(pid: int) -> bool:
    """Return whether pid is running.

    Integration: Called by ``_iter_workspace_gateway_pids``, ``stop_gateway_process`` and
    collaborates with ``kernel32.OpenProcess``, ``ctypes.c_ulong``,
    ``kernel32.GetExitCodeProcess``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if sys.platform == "win32":
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == 259  # STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    else:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


def _iter_workspace_gateway_pids(workspace: str | Path | None = None) -> list[int]:
    """Iterate over workspace gateway pids for the enclosing subsystem.

    Integration: Called by ``stop_gateway_process``, ``gateway_status`` and collaborates with
    ``get_workspace_root``, ``os.getpid``, ``result.stdout.splitlines``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve argv boundaries, timeouts, and child cleanup; preserve exception and
    fallback behavior expected by callers.
    """
    root = str(get_workspace_root(workspace))
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["wmic", "process", "where",
                 f"commandline like '%-m ohmo gateway run%' and commandline like '%--workspace {root}%'",
                 "get", "processid"],
                capture_output=True, text=True, check=True,
            )
        except Exception:
            return []
        current_pid = os.getpid()
        pids: list[int] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.lower() == "processid":
                continue
            try:
                pid = int(line)
            except ValueError:
                continue
            if pid == current_pid:
                continue
            if _pid_is_running(pid):
                pids.append(pid)
        return pids
    else:
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid=,args="],
                capture_output=True,
                text=True,
                check=True,
            )
        except Exception:
            return []

        current_pid = os.getpid()
        pids = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pid_text, args = line.split(None, 1)
                pid = int(pid_text)
            except ValueError:
                continue
            if pid == current_pid:
                continue
            if "-m ohmo gateway run" not in args:
                continue
            if f"--workspace {root}" not in args:
                continue
            if _pid_is_running(pid):
                pids.append(pid)
        return pids


def stop_gateway_process(cwd: str | Path | None = None, workspace: str | Path | None = None) -> bool:
    """Stop the background gateway process if present.

    Integration: Called by ``_maybe_restart_gateway``, ``gateway_stop_cmd`` and collaborates
    with ``OhmoGatewayService``, ``service.pid_file.exists``, ``pids.extend``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    argv boundaries, timeouts, and child cleanup; preserve exception and fallback behavior
    expected by callers.
    """
    service = OhmoGatewayService(cwd, workspace)
    pids: list[int] = []
    if service.pid_file.exists():
        try:
            pids.append(int(service.pid_file.read_text(encoding="utf-8").strip()))
        except ValueError:
            pass
    pids.extend(_iter_workspace_gateway_pids(workspace))
    unique_pids = []
    for pid in pids:
        if pid not in unique_pids and _pid_is_running(pid):
            unique_pids.append(pid)
    if not unique_pids:
        service.pid_file.unlink(missing_ok=True)
        return False
    if sys.platform == "win32":
        for pid in unique_pids:
            with contextlib.suppress(Exception):
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    check=False,
                )
    else:
        for pid in unique_pids:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
    service.pid_file.unlink(missing_ok=True)
    service.write_state(running=False)
    return True


def gateway_status(cwd: str | Path | None = None, workspace: str | Path | None = None) -> GatewayState:
    """Load the last known gateway state.

    Integration: Called by ``_maybe_restart_gateway``, ``gateway_status_cmd`` and collaborates
    with ``OhmoGatewayService``, ``service.pid_file.exists``, ``service.state_file.exists``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    exception and fallback behavior expected by callers.
    """
    service = OhmoGatewayService(cwd, workspace)
    live_pid: int | None = None
    if service.pid_file.exists():
        try:
            pid = int(service.pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = None
        if pid is not None and _pid_is_running(pid):
            live_pid = pid
    if live_pid is None:
        live_pids = _iter_workspace_gateway_pids(workspace)
        if live_pids:
            live_pid = live_pids[0]
            service.pid_file.write_text(str(live_pid), encoding="utf-8")
        else:
            service.pid_file.unlink(missing_ok=True)

    active_sessions = 0
    last_error: str | None = None
    if service.state_file.exists():
        with contextlib.suppress(Exception):
            state = GatewayState.model_validate_json(service.state_file.read_text(encoding="utf-8"))
            active_sessions = state.active_sessions
            last_error = state.last_error

    return GatewayState(
        running=live_pid is not None,
        pid=live_pid,
        active_sessions=active_sessions,
        provider_profile=service._config.provider_profile,
        enabled_channels=service._config.enabled_channels,
        last_error=last_error,
    )
