"""Secure local HTTP host for the OpenHarness browser interface."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import re
import secrets
import signal
import webbrowser
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from aiohttp import WSMsgType, web
from pydantic import ValidationError

from openharness.ui.backend_host import BackendHostConfig, EventSink, ReactBackendHost, RequestSource
from openharness.ui.protocol import BackendEvent, FrontendRequest
from openharness.ui.web_models import WebBootstrap, build_web_bootstrap
from openharness.ui.web_resources import WebResourceService

log = logging.getLogger(__name__)

_WEB_TEXT_LIMIT = 64_000
_SECRET_KEY_RE = re.compile(
    r"(?:^|_)(?:api_?key|access_?token|auth_?token|authorization|credential|password|"
    r"private_?key|refresh_?token|secret|token)(?:$|_)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"gh[pousr]_[A-Za-z0-9]{16,}|AKIA[A-Z0-9]{16,})",
    re.IGNORECASE,
)
_INLINE_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|authorization|credential|password|"
    r"private[_-]?key|refresh[_-]?token|secret|token)\s*[:=]\s*([^\s,;]+)"
)
_AUTH_HEADER_RE = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+")


_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self' ws: wss:; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


class WebServerConfigurationError(ValueError):
    """Raised when local-only hosting or asset requirements are violated."""


@dataclass(frozen=True, slots=True)
class WebServerConfig:
    """Validated launch configuration for one local web host."""

    cwd: Path
    host: str = "127.0.0.1"
    port: int = 0
    open_browser: bool = True
    assets_dir: Path | None = None
    token: str | None = None
    reconnect_grace_seconds: float = 5.0

    def __post_init__(self) -> None:
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError as exc:
            raise WebServerConfigurationError(
                "The web UI host must be a loopback IP address such as 127.0.0.1"
            ) from exc
        if not address.is_loopback:
            raise WebServerConfigurationError(
                "The first web UI release is local-only; --host must be a loopback address"
            )
        if not 0 <= self.port <= 65535:
            raise WebServerConfigurationError("--port must be between 0 and 65535")
        if not 0 <= self.reconnect_grace_seconds <= 30:
            raise WebServerConfigurationError("reconnect_grace_seconds must be between 0 and 30")


BootstrapFactory = Callable[[Path], WebBootstrap]


class RuntimeController(Protocol):
    """Minimal lifecycle implemented by the shared structured backend host."""

    async def run(self) -> int: ...


ControllerFactory = Callable[
    [BackendHostConfig, RequestSource, EventSink],
    RuntimeController,
]


def _bounded_web_text(value: str) -> str:
    redacted = _SECRET_VALUE_RE.sub("[REDACTED]", value)
    redacted = _INLINE_SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    redacted = _AUTH_HEADER_RE.sub("[REDACTED]", redacted)
    if redacted.lower().startswith(("bearer ", "basic ")):
        redacted = "[REDACTED]"
    if len(redacted) <= _WEB_TEXT_LIMIT:
        return redacted
    return f"{redacted[:_WEB_TEXT_LIMIT]}\n… [truncated for browser display]"


def _redact_web_value(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _SECRET_KEY_RE.search(key.replace("-", "_")):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact_web_value(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact_web_value(item) for item in value]
    if isinstance(value, str):
        return _bounded_web_text(value)
    return value


def _web_safe_event(event: BackendEvent) -> BackendEvent:
    """Return a bounded, credential-redacted presentation copy for the browser."""

    updates: dict[str, Any] = {}
    if event.message is not None:
        updates["message"] = _bounded_web_text(event.message)
    if event.output is not None:
        updates["output"] = _bounded_web_text(event.output)
    if event.tool_input is not None:
        updates["tool_input"] = _redact_web_value(event.tool_input)
    if event.state is not None:
        state = _redact_web_value(event.state)
        if isinstance(state, dict):
            state.pop("base_url", None)
        updates["state"] = state
    if event.modal is not None:
        updates["modal"] = _redact_web_value(event.modal)
    if event.item is not None:
        updates["item"] = event.item.model_copy(
            update={
                "text": _bounded_web_text(event.item.text),
                "tool_input": (
                    _redact_web_value(event.item.tool_input)
                    if event.item.tool_input is not None
                    else None
                ),
            }
        )
    return event.model_copy(update=updates)


def _default_controller_factory(
    config: BackendHostConfig,
    request_source: RequestSource,
    event_sink: EventSink,
) -> RuntimeController:
    return ReactBackendHost(
        config,
        request_source=request_source,
        event_sink=event_sink,
    )


class WebRuntimeSession:
    """Bridge one transport-neutral runtime controller across socket reconnects."""

    def __init__(
        self,
        config: BackendHostConfig,
        controller_factory: ControllerFactory,
        *,
        reconnect_grace_seconds: float,
    ) -> None:
        self._config = config
        self._controller_factory = controller_factory
        self._reconnect_grace_seconds = reconnect_grace_seconds
        self._requests: asyncio.Queue[FrontendRequest | None] = asyncio.Queue(maxsize=128)
        self._buffered_events: deque[BackendEvent] = deque(maxlen=256)
        self._socket: web.WebSocketResponse | None = None
        self._controller_task: asyncio.Task[int] | None = None
        self._controller: RuntimeController | None = None
        self._grace_task: asyncio.Task[None] | None = None
        self._socket_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._socket is not None and not self._socket.closed

    @property
    def started(self) -> bool:
        return self._controller_task is not None

    @property
    def done(self) -> bool:
        return self._controller_task is not None and self._controller_task.done()

    @property
    def runtime_bundle(self) -> Any | None:
        return getattr(self._controller, "runtime_bundle", None)

    async def attach(self, socket: web.WebSocketResponse) -> bool:
        """Attach the sole controlling socket and replay bounded missed events."""

        async with self._socket_lock:
            if self.connected:
                return False
            reconnecting = self.started and not self.done
            grace, self._grace_task = self._grace_task, None
            if grace is not None:
                grace.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await grace
            self._socket = socket
            while self._buffered_events:
                await socket.send_str(self._buffered_events.popleft().model_dump_json())
            if not self.started:
                controller = self._controller_factory(
                    self._config,
                    self.read_request,
                    self.emit_event,
                )
                self._controller = controller
                self._controller_task = asyncio.create_task(self._run_controller(controller))
            return reconnecting

    async def detach(self, socket: web.WebSocketResponse) -> None:
        """Start a bounded reclaim window when the controlling socket disappears."""

        async with self._socket_lock:
            if self._socket is not socket:
                return
            self._socket = None
            if not self.done and self._grace_task is None:
                self._grace_task = asyncio.create_task(self._expire_after_grace())

    async def submit(self, request: FrontendRequest) -> bool:
        """Queue one validated request without allowing unbounded client pressure."""

        try:
            self._requests.put_nowait(request)
            return True
        except asyncio.QueueFull:
            return False

    async def read_request(self) -> FrontendRequest | None:
        return await self._requests.get()

    async def emit_event(self, event: BackendEvent) -> None:
        """Send an event to the controller socket or retain a bounded reconnect tail."""

        event = _web_safe_event(event)
        async with self._socket_lock:
            socket = self._socket
            if socket is None or socket.closed:
                self._buffered_events.append(event)
                return
            try:
                await socket.send_str(event.model_dump_json())
            except (ConnectionError, RuntimeError):
                self._buffered_events.append(event)

    async def close(self) -> None:
        """Close the socket, release controller waits, and await runtime cleanup."""

        grace, self._grace_task = self._grace_task, None
        if grace is not None:
            grace.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await grace
        socket, self._socket = self._socket, None
        if socket is not None and not socket.closed:
            await socket.close(code=1001, message=b"Local host shutting down")
        if not self.done:
            await self._put_shutdown()
        task = self._controller_task
        if task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
            except asyncio.TimeoutError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def _expire_after_grace(self) -> None:
        try:
            await asyncio.sleep(self._reconnect_grace_seconds)
            await self._put_shutdown()
        except asyncio.CancelledError:
            raise
        finally:
            self._grace_task = None

    async def _put_shutdown(self) -> None:
        await self._requests.put(None)

    async def _run_controller(self, controller: RuntimeController) -> int:
        try:
            return await controller.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Local web runtime controller failed")
            await self.emit_event(
                BackendEvent(
                    type="error",
                    message="The local runtime could not start. Check the terminal log for details.",
                )
            )
            await self.emit_event(BackendEvent(type="shutdown"))
            return 1
        finally:
            async with self._socket_lock:
                socket = self._socket
            if socket is not None and not socket.closed:
                await socket.close()


class WebUiServer:
    """Own the aiohttp runner, bound socket, authorization, and shutdown order."""

    def __init__(
        self,
        config: WebServerConfig,
        *,
        bootstrap_factory: BootstrapFactory = build_web_bootstrap,
        backend_config: BackendHostConfig | None = None,
        controller_factory: ControllerFactory = _default_controller_factory,
    ) -> None:
        self.config = config
        self.token = config.token or secrets.token_urlsafe(32)
        self._bootstrap_factory = bootstrap_factory
        self._backend_config = backend_config or BackendHostConfig(cwd=str(config.cwd))
        self._controller_factory = controller_factory
        self._resource_service = WebResourceService(config.cwd)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._port: int | None = None
        self._allowed_authorities: set[str] = set()
        self._allowed_origins: set[str] = set()
        self._runtime_session: WebRuntimeSession | None = None
        self._runtime_session_lock = asyncio.Lock()
        self._assets_dir = self._resolve_assets_dir(config.assets_dir)
        self._app = self._create_app()

    @staticmethod
    def _resolve_assets_dir(explicit: Path | None) -> Path:
        assets = explicit or Path(__file__).resolve().parents[1] / "_web"
        assets = assets.expanduser().resolve()
        if not (assets / "index.html").is_file() or not (assets / "assets").is_dir():
            raise WebServerConfigurationError(
                f"Web UI assets are missing at {assets}. Run `npm run build` in frontend/web."
            )
        return assets

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("The web UI server has not started")
        return self._port

    @property
    def origin(self) -> str:
        host = f"[{self.config.host}]" if ":" in self.config.host else self.config.host
        return f"http://{host}:{self.port}"

    @property
    def launch_url(self) -> str:
        return f"{self.origin}/#token={self.token}"

    def _create_app(self) -> web.Application:
        app = web.Application(
            middlewares=[self._security_headers, self._validate_host, self._authorize_api],
            client_max_size=1_048_576,
        )
        app.router.add_get("/api/bootstrap", self._handle_bootstrap)
        app.router.add_get("/api/health", self._handle_health)
        app.router.add_get("/api/session", self._handle_session)
        app.router.add_get("/api/{area:sessions|capabilities|work|knowledge|autopilot}", self._handle_resource)
        app.router.add_post("/api/actions/{name}", self._handle_action)
        app.router.add_static("/assets", self._assets_dir / "assets", show_index=False)
        app.router.add_get("/{path:.*}", self._handle_index)
        return app

    @web.middleware
    async def _security_headers(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            # Framework-generated 404/421 responses still cross the same browser
            # security boundary and must carry the host policy headers.
            response = exc
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif request.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

    @web.middleware
    async def _validate_host(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        if self._allowed_authorities and request.host not in self._allowed_authorities:
            raise web.HTTPMisdirectedRequest(text="Unrecognized local host")
        return await handler(request)

    @web.middleware
    async def _authorize_api(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        if not request.path.startswith("/api/"):
            return await handler(request)

        origin = request.headers.get("Origin")
        if origin is not None and origin not in self._allowed_origins:
            return web.json_response(
                {"error": {"code": "origin_denied", "message": "Cross-origin access is not allowed"}},
                status=403,
            )
        if request.path == "/api/session":
            if origin is None:
                return web.json_response(
                    {"error": {"code": "origin_required", "message": "WebSocket Origin is required"}},
                    status=403,
                )
            return await handler(request)

        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin is None:
            return web.json_response(
                {"error": {"code": "origin_required", "message": "Mutation Origin is required"}},
                status=403,
            )

        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {self.token}"
        if not secrets.compare_digest(supplied, expected):
            return web.json_response(
                {"error": {"code": "unauthorized", "message": "A valid launch token is required"}},
                status=401,
            )
        return await handler(request)

    async def _handle_bootstrap(self, request: web.Request) -> web.Response:
        del request
        snapshot = await asyncio.to_thread(self._bootstrap_factory, self.config.cwd)
        return web.json_response(_redact_web_value(snapshot.model_dump(mode="json")))

    async def _handle_health(self, request: web.Request) -> web.Response:
        del request
        return web.json_response({"status": "ok", "schema_version": 1})

    async def _handle_resource(self, request: web.Request) -> web.Response:
        area = request.match_info["area"]
        async with self._runtime_session_lock:
            bundle = self._runtime_session.runtime_bundle if self._runtime_session is not None else None
        try:
            snapshot = await asyncio.to_thread(
                self._resource_service.snapshot,
                area,
                runtime_bundle=bundle,
            )
        except Exception:
            log.exception("Failed to build web resource snapshot for %s", area)
            return web.json_response(
                {"error": {"code": "resource_unavailable", "message": f"Could not load {area}"}},
                status=500,
            )
        return web.json_response(_redact_web_value(snapshot.model_dump(mode="json")))

    async def _handle_action(self, request: web.Request) -> web.Response:
        name = request.match_info["name"]
        try:
            payload = await request.json()
        except (TypeError, ValueError):
            return web.json_response(
                {"error": {"code": "invalid_json", "message": "Action body must be JSON"}},
                status=400,
            )
        try:
            result = await self._resource_service.action(name, payload)
        except KeyError:
            return web.json_response(
                {"error": {"code": "unknown_action", "message": "Action is not allowed"}},
                status=404,
            )
        except ValidationError:
            return web.json_response(
                {"error": {"code": "invalid_action", "message": "Action input is invalid"}},
                status=400,
            )
        except ValueError:
            return web.json_response(
                {
                    "error": {
                        "code": "invalid_action",
                        "message": "Action target is invalid or unavailable",
                    }
                },
                status=400,
            )
        except Exception:
            log.exception("Web action %s failed", name)
            return web.json_response(
                {"error": {"code": "action_failed", "message": "The action could not be completed"}},
                status=500,
            )
        return web.json_response(_redact_web_value(result.model_dump(mode="json")))

    async def _handle_session(self, request: web.Request) -> web.StreamResponse:
        socket = web.WebSocketResponse(max_msg_size=10 * 1024 * 1024, heartbeat=30)
        await socket.prepare(request)
        try:
            auth_message = await socket.receive(timeout=5)
        except asyncio.TimeoutError:
            await socket.close(code=4401, message=b"Authentication timed out")
            return socket
        if auth_message.type != WSMsgType.TEXT:
            await socket.close(code=4401, message=b"Authentication is required")
            return socket
        try:
            raw_auth = auth_message.json()
            if isinstance(raw_auth, dict):
                supplied = str(raw_auth.get("token", ""))
                is_auth_message = raw_auth.get("type") == "authenticate"
            else:
                supplied = ""
                is_auth_message = False
        except (TypeError, ValueError):
            supplied = ""
            is_auth_message = False
        if not is_auth_message or not secrets.compare_digest(supplied, self.token):
            await socket.close(code=4401, message=b"Invalid launch token")
            return socket

        async with self._runtime_session_lock:
            session = self._runtime_session
            if session is None or session.done:
                session = WebRuntimeSession(
                    self._backend_config,
                    self._controller_factory,
                    reconnect_grace_seconds=self.config.reconnect_grace_seconds,
                )
                self._runtime_session = session
            if session.connected:
                await socket.send_json(
                    {"type": "error", "message": "Another browser tab controls this runtime."}
                )
                await socket.close(code=4409, message=b"Runtime already controlled")
                return socket
            reconnected = session.started and not session.done
            await socket.send_json(
                {"type": "authenticated", "schema_version": 1, "reconnected": reconnected}
            )
            await session.attach(socket)

        try:
            async for message in socket:
                if message.type == WSMsgType.TEXT:
                    try:
                        frontend_request = FrontendRequest.model_validate_json(message.data)
                    except Exception:
                        await socket.send_json(
                            {"type": "error", "message": "Invalid session request"}
                        )
                        continue
                    if not await session.submit(frontend_request):
                        await socket.send_json(
                            {"type": "error", "message": "Session request queue is full"}
                        )
                        await socket.close(code=4429, message=b"Too many queued requests")
                        break
                elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                    break
        finally:
            await session.detach(socket)
        return socket

    async def _handle_index(self, request: web.Request) -> web.StreamResponse:
        if request.path.startswith("/api/") or request.path.startswith("/assets/"):
            raise web.HTTPNotFound()
        return web.FileResponse(self._assets_dir / "index.html")

    async def start(self) -> None:
        """Bind the configured loopback socket and establish exact origin policy."""

        if self._runner is not None:
            raise RuntimeError("The web UI server is already running")
        runner = web.AppRunner(self._app, access_log=None)
        try:
            await runner.setup()
            site = web.TCPSite(runner, self.config.host, self.config.port)
            await site.start()
            server = site._server
            if server is None or not server.sockets:
                raise RuntimeError("The web UI server did not expose a listening socket")
            self._port = int(server.sockets[0].getsockname()[1])
            authority_host = (
                f"[{self.config.host}]" if ":" in self.config.host else self.config.host
            )
            authority = f"{authority_host}:{self._port}"
            self._allowed_authorities = {authority}
            self._allowed_origins = {f"http://{authority}"}
            self._runner = runner
            self._site = site
        except BaseException:
            await runner.cleanup()
            self._port = None
            raise

    async def close(self) -> None:
        """Idempotently stop accepting requests and release all server resources."""

        async with self._runtime_session_lock:
            session, self._runtime_session = self._runtime_session, None
        if session is not None:
            await session.close()
        runner, self._runner = self._runner, None
        self._site = None
        self._port = None
        self._allowed_authorities.clear()
        self._allowed_origins.clear()
        if runner is not None:
            await runner.cleanup()

    async def __aenter__(self) -> "WebUiServer":
        await self.start()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        del exc_info
        await self.close()


async def run_web_ui(config: WebServerConfig) -> None:
    """Run one local host until SIGINT/SIGTERM while preserving cleanup ownership."""

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals: list[signal.Signals] = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stop_event.set)
            installed_signals.append(signum)

    try:
        async with WebUiServer(config) as server:
            print(f"OpenHarness web UI: {server.launch_url}", flush=True)
            print("Press Ctrl+C to stop.", flush=True)
            if config.open_browser:
                await asyncio.to_thread(webbrowser.open, server.launch_url)
            await stop_event.wait()
    finally:
        for signum in installed_signals:
            with contextlib.suppress(NotImplementedError):
                loop.remove_signal_handler(signum)
