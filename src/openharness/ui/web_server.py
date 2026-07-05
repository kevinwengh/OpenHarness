"""Secure local HTTP host for the OpenHarness browser interface."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import secrets
import signal
import webbrowser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from openharness.ui.web_models import WebBootstrap, build_web_bootstrap


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


BootstrapFactory = Callable[[Path], WebBootstrap]


class WebUiServer:
    """Own the aiohttp runner, bound socket, authorization, and shutdown order."""

    def __init__(
        self,
        config: WebServerConfig,
        *,
        bootstrap_factory: BootstrapFactory = build_web_bootstrap,
    ) -> None:
        self.config = config
        self.token = config.token or secrets.token_urlsafe(32)
        self._bootstrap_factory = bootstrap_factory
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._port: int | None = None
        self._allowed_authorities: set[str] = set()
        self._allowed_origins: set[str] = set()
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

        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {self.token}"
        if not secrets.compare_digest(supplied, expected):
            return web.json_response(
                {"error": {"code": "unauthorized", "message": "A valid launch token is required"}},
                status=401,
            )

        origin = request.headers.get("Origin")
        if origin is not None and origin not in self._allowed_origins:
            return web.json_response(
                {"error": {"code": "origin_denied", "message": "Cross-origin access is not allowed"}},
                status=403,
            )
        return await handler(request)

    async def _handle_bootstrap(self, request: web.Request) -> web.Response:
        del request
        snapshot = await asyncio.to_thread(self._bootstrap_factory, self.config.cwd)
        return web.json_response(snapshot.model_dump(mode="json"))

    async def _handle_health(self, request: web.Request) -> web.Response:
        del request
        return web.json_response({"status": "ok", "schema_version": 1})

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
