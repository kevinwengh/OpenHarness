"""Contracts for the secure local web UI host and redacted bootstrap."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import WSServerHandshakeError
from typer.testing import CliRunner

from openharness.api.client import ApiMessageCompleteEvent
from openharness.api.usage import UsageSnapshot
from openharness.cli import app
from openharness.config.settings import ProviderProfile, Settings
from openharness.engine.messages import ConversationMessage, TextBlock
from openharness.ui.backend_host import BackendHostConfig
from openharness.ui.protocol import BackendEvent, FrontendRequest
from openharness.ui.web_models import build_web_bootstrap
from openharness.ui.web_resources import WebResourceSnapshot
from openharness.ui.web_server import (
    WebServerConfig,
    WebServerConfigurationError,
    WebRuntimeSession,
    WebUiServer,
)


class _AuthManager:
    def __init__(self, *, configured: bool = True) -> None:
        self.configured = configured

    def get_profile_statuses(self):
        return {
            "local": {
                "configured": self.configured,
                "auth_source": "local_token",
                "base_url": "http://secret-endpoint.invalid",
            }
        }


class _StaticApiClient:
    async def stream_message(self, request):
        del request
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(
                role="assistant",
                content=[TextBlock(text="hello from the browser runtime")],
            ),
            usage=UsageSnapshot(input_tokens=2, output_tokens=4),
            stop_reason=None,
        )


class _FakeController:
    def __init__(self, request_source, event_sink, state) -> None:
        self._request_source = request_source
        self._event_sink = event_sink
        self._state = state

    async def run(self) -> int:
        self._state["starts"] += 1
        await self._event_sink(BackendEvent(type="assistant_delta", message="controller-ready"))
        while True:
            request = await self._request_source()
            if request is None:
                break
            self._state["requests"].append(request)
            if request.type == "submit_line":
                await self._event_sink(BackendEvent(type="assistant_delta", message=request.line))
                await self._event_sink(BackendEvent(type="line_complete"))
            if request.type == "shutdown":
                break
        self._state["stops"] += 1
        self._state["stopped"].set()
        return 0


class _FakeSocket:
    def __init__(self) -> None:
        self.closed = False
        self.messages: list[str] = []

    async def send_str(self, value: str) -> None:
        self.messages.append(value)

    async def close(self, **_kwargs) -> None:
        self.closed = True


def _controller_factory(state):
    def _factory(config, request_source, event_sink):
        del config
        return _FakeController(request_source, event_sink, state)

    return _factory


@pytest.fixture
def assets_dir(tmp_path: Path) -> Path:
    assets = tmp_path / "web"
    (assets / "assets").mkdir(parents=True)
    (assets / "index.html").write_text(
        "<!doctype html><html><body><div id='root'></div></body></html>",
        encoding="utf-8",
    )
    (assets / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    return assets


def _settings() -> Settings:
    return Settings(
        api_key="top-secret-api-key",
        base_url="http://secret-endpoint.invalid",
        active_profile="local",
        profiles={
            "local": ProviderProfile(
                label="Local model",
                provider="anthropic",
                api_format="anthropic",
                auth_source="local_token",
                default_model="local-model",
                last_model="local-model",
                base_url="http://secret-endpoint.invalid",
            )
        },
    ).materialize_active_profile()


def test_bootstrap_is_versioned_and_credential_redacted(tmp_path: Path):
    snapshot = build_web_bootstrap(
        tmp_path,
        settings=_settings(),
        auth_manager=_AuthManager(),
    )

    payload = snapshot.model_dump(mode="json")
    serialized = snapshot.model_dump_json()
    assert payload["schema_version"] == 1
    assert payload["runtime"]["profile"] == "local"
    assert payload["runtime"]["auth"] == {
        "state": "configured",
        "label": "local_token",
    }
    assert len(payload["navigation"]) == 8
    assert all(item["availability"] == "available" for item in payload["navigation"])
    assert "top-secret-api-key" not in serialized
    assert "secret-endpoint" not in serialized
    assert "api_key" not in serialized
    assert "base_url" not in serialized


def test_bootstrap_degrades_auth_inspection_without_leaking_error(tmp_path: Path):
    manager = SimpleNamespace(
        get_profile_statuses=lambda: (_ for _ in ()).throw(
            RuntimeError("credential path /private/example")
        )
    )

    snapshot = build_web_bootstrap(tmp_path, settings=_settings(), auth_manager=manager)

    assert snapshot.runtime.auth.state == "unknown"
    assert "/private/example" not in snapshot.model_dump_json()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.2", "example.com"])
def test_server_rejects_non_loopback_hosts(host: str, tmp_path: Path):
    with pytest.raises(WebServerConfigurationError, match="loopback|local-only"):
        WebServerConfig(cwd=tmp_path, host=host)


def test_server_requires_packaged_assets(tmp_path: Path):
    with pytest.raises(WebServerConfigurationError, match="assets are missing"):
        WebUiServer(WebServerConfig(cwd=tmp_path, assets_dir=tmp_path / "missing"))


@pytest.mark.asyncio
async def test_api_requires_token_and_exact_origin(assets_dir: Path, tmp_path: Path):
    snapshot = build_web_bootstrap(
        tmp_path,
        settings=_settings(),
        auth_manager=_AuthManager(),
    )
    server = WebUiServer(
        WebServerConfig(
            cwd=tmp_path,
            assets_dir=assets_dir,
            token="test-launch-token",
            open_browser=False,
        ),
        bootstrap_factory=lambda _cwd: snapshot,
    )

    async with server, aiohttp.ClientSession() as client:
        unauthorized = await client.get(f"{server.origin}/api/bootstrap")
        assert unauthorized.status == 401
        assert (await unauthorized.json())["error"]["code"] == "unauthorized"

        headers = {"Authorization": "Bearer test-launch-token"}
        denied = await client.get(
            f"{server.origin}/api/bootstrap",
            headers={**headers, "Origin": "http://attacker.invalid"},
        )
        assert denied.status == 403
        assert (await denied.json())["error"]["code"] == "origin_denied"

        allowed = await client.get(
            f"{server.origin}/api/bootstrap",
            headers={**headers, "Origin": server.origin},
        )
        assert allowed.status == 200
        assert (await allowed.json())["schema_version"] == 1


@pytest.mark.asyncio
async def test_server_applies_security_headers_and_serves_spa_routes(
    assets_dir: Path,
    tmp_path: Path,
):
    server = WebUiServer(
        WebServerConfig(cwd=tmp_path, assets_dir=assets_dir, open_browser=False),
        bootstrap_factory=lambda _cwd: build_web_bootstrap(
            tmp_path,
            settings=_settings(),
            auth_manager=_AuthManager(),
        ),
    )

    async with server, aiohttp.ClientSession() as client:
        page = await client.get(f"{server.origin}/workbench")
        assert page.status == 200
        assert "<div id='root'>" in await page.text()
        assert page.headers["Content-Security-Policy"].startswith("default-src 'self'")
        assert page.headers["X-Content-Type-Options"] == "nosniff"
        assert page.headers["Referrer-Policy"] == "no-referrer"
        assert page.headers["X-Frame-Options"] == "DENY"
        assert page.headers["Cache-Control"] == "no-cache"

        missing = await client.get(f"{server.origin}/assets/missing.js")
        assert missing.status == 404
        assert missing.headers["Content-Security-Policy"].startswith("default-src 'self'")
        assert missing.headers["Cache-Control"] == "public, max-age=31536000, immutable"

        health = await client.get(
            f"{server.origin}/api/health",
            headers={"Authorization": f"Bearer {server.token}"},
        )
        assert health.status == 200
        assert health.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_server_has_single_idempotent_lifecycle_owner(assets_dir: Path, tmp_path: Path):
    server = WebUiServer(
        WebServerConfig(cwd=tmp_path, assets_dir=assets_dir, open_browser=False)
    )

    await server.start()
    assert server.port > 0
    with pytest.raises(RuntimeError, match="already running"):
        await server.start()
    await server.close()
    await server.close()
    with pytest.raises(RuntimeError, match="has not started"):
        _ = server.port


@pytest.mark.asyncio
async def test_websocket_requires_origin_and_first_message_token(assets_dir: Path, tmp_path: Path):
    state = {"starts": 0, "stops": 0, "requests": [], "stopped": asyncio.Event()}
    server = WebUiServer(
        WebServerConfig(
            cwd=tmp_path,
            assets_dir=assets_dir,
            token="socket-token",
            open_browser=False,
            reconnect_grace_seconds=0,
        ),
        backend_config=BackendHostConfig(cwd=str(tmp_path)),
        controller_factory=_controller_factory(state),
    )

    async with server, aiohttp.ClientSession() as client:
        with pytest.raises(WSServerHandshakeError) as denied:
            await client.ws_connect(f"{server.origin}/api/session")
        assert denied.value.status == 403

        unauthorized = await client.ws_connect(
            f"{server.origin}/api/session",
            origin=server.origin,
        )
        await unauthorized.send_json({"type": "authenticate", "token": "wrong"})
        closed = await unauthorized.receive()
        assert closed.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}

        malformed = await client.ws_connect(
            f"{server.origin}/api/session",
            origin=server.origin,
        )
        await malformed.send_json(["authenticate", "socket-token"])
        malformed_closed = await malformed.receive()
        assert malformed_closed.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}

        socket = await client.ws_connect(f"{server.origin}/api/session", origin=server.origin)
        await socket.send_json({"type": "authenticate", "token": "socket-token"})
        authenticated = await socket.receive_json()
        assert authenticated == {
            "type": "authenticated",
            "schema_version": 1,
            "reconnected": False,
        }
        assert (await socket.receive_json())["message"] == "controller-ready"
        await socket.send_str(FrontendRequest(type="submit_line", line="hello").model_dump_json())
        assert (await socket.receive_json())["message"] == "hello"
        assert (await socket.receive_json())["type"] == "line_complete"

        competing = await client.ws_connect(f"{server.origin}/api/session", origin=server.origin)
        await competing.send_json({"type": "authenticate", "token": "socket-token"})
        assert (await competing.receive_json())["message"] == "Another browser tab controls this runtime."
        assert state["starts"] == 1
        await socket.close()


@pytest.mark.asyncio
async def test_runtime_session_reconnects_and_replays_bounded_events(tmp_path: Path):
    state = {"starts": 0, "stops": 0, "requests": [], "stopped": asyncio.Event()}
    session = WebRuntimeSession(
        BackendHostConfig(cwd=str(tmp_path)),
        _controller_factory(state),
        reconnect_grace_seconds=0.02,
    )
    first = _FakeSocket()
    second = _FakeSocket()

    assert await session.attach(first) is False
    await asyncio.sleep(0)
    assert state["starts"] == 1
    await session.detach(first)
    await session.emit_event(BackendEvent(type="assistant_delta", message="while-away"))
    assert await session.attach(second) is True
    assert any("while-away" in message for message in second.messages)
    assert state["starts"] == 1

    await session.detach(second)
    await asyncio.wait_for(state["stopped"].wait(), timeout=1)
    assert state["stops"] == 1
    await session.close()


@pytest.mark.asyncio
async def test_runtime_session_redacts_browser_event_secrets(tmp_path: Path):
    state = {"starts": 0, "stops": 0, "requests": [], "stopped": asyncio.Event()}
    session = WebRuntimeSession(
        BackendHostConfig(cwd=str(tmp_path)),
        _controller_factory(state),
        reconnect_grace_seconds=0,
    )
    socket = _FakeSocket()
    await session.attach(socket)
    await session.emit_event(
        BackendEvent(
            type="state_snapshot",
            state={"model": "safe-model", "base_url": "https://user:secret@example.test"},
            tool_input={"api_key": "secret-value", "nested": {"token": "secret-token"}},
            message="api_key=plain-value Bearer should-not-appear",
        )
    )

    payload = next(message for message in socket.messages if "safe-model" in message)
    assert "base_url" not in payload
    assert "secret-value" not in payload
    assert "secret-token" not in payload
    assert "should-not-appear" not in payload
    assert "plain-value" not in payload
    assert payload.count("[REDACTED]") >= 3
    await session.close()


@pytest.mark.asyncio
async def test_websocket_runs_shared_runtime_end_to_end(
    assets_dir: Path,
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENHARNESS_LOGS_DIR", str(tmp_path / "logs"))
    server = WebUiServer(
        WebServerConfig(
            cwd=tmp_path,
            assets_dir=assets_dir,
            token="runtime-token",
            open_browser=False,
            reconnect_grace_seconds=0,
        ),
        backend_config=BackendHostConfig(
            cwd=str(tmp_path),
            api_client=_StaticApiClient(),
        ),
    )

    async with server, aiohttp.ClientSession() as client:
        socket = await client.ws_connect(f"{server.origin}/api/session", origin=server.origin)
        await socket.send_json({"type": "authenticate", "token": "runtime-token"})
        assert (await socket.receive_json())["type"] == "authenticated"

        startup_events = []
        while not any(event["type"] == "ready" for event in startup_events):
            startup_events.append(await asyncio.wait_for(socket.receive_json(), timeout=5))
        await socket.send_str(FrontendRequest(type="submit_line", line="hello").model_dump_json())

        turn_events = []
        while not any(event["type"] == "line_complete" for event in turn_events):
            turn_events.append(await asyncio.wait_for(socket.receive_json(), timeout=5))
        assert any(
            event["type"] == "transcript_item"
            and event.get("item", {}).get("role") == "user"
            for event in turn_events
        )
        assert any(
            event["type"] == "assistant_complete"
            and event["message"] == "hello from the browser runtime"
            for event in turn_events
        )
        await socket.close()


@pytest.mark.asyncio
async def test_resource_and_action_routes_require_auth_origin_and_allowlist(
    assets_dir: Path,
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENHARNESS_LOGS_DIR", str(tmp_path / "logs"))
    server = WebUiServer(
        WebServerConfig(
            cwd=tmp_path,
            assets_dir=assets_dir,
            token="resource-token",
            open_browser=False,
        )
    )
    original_snapshot = server._resource_service.snapshot

    def resource_snapshot(area, *, runtime_bundle=None):
        if area == "knowledge":
            return WebResourceSnapshot(
                area="knowledge",
                data={"api_key": "resource-secret", "preview": "Bearer inline-secret"},
            )
        return original_snapshot(area, runtime_bundle=runtime_bundle)

    server._resource_service.snapshot = resource_snapshot

    async with server, aiohttp.ClientSession() as client:
        headers = {"Authorization": "Bearer resource-token"}
        knowledge = await client.get(f"{server.origin}/api/knowledge", headers=headers)
        assert knowledge.status == 200
        knowledge_payload = await knowledge.text()
        assert '"area": "knowledge"' in knowledge_payload
        assert "resource-secret" not in knowledge_payload
        assert "inline-secret" not in knowledge_payload

        missing_origin = await client.post(
            f"{server.origin}/api/actions/autopilot.enqueue",
            headers=headers,
            json={"title": "Browser task"},
        )
        assert missing_origin.status == 403

        mutation_headers = {**headers, "Origin": server.origin}
        unknown = await client.post(
            f"{server.origin}/api/actions/python.call",
            headers=mutation_headers,
            json={"name": "anything"},
        )
        assert unknown.status == 404
        assert (await unknown.json())["error"]["code"] == "unknown_action"

        invalid = await client.post(
            f"{server.origin}/api/actions/autopilot.enqueue",
            headers=mutation_headers,
            json={"title": "", "api_key": "must-not-echo"},
        )
        assert invalid.status == 400
        invalid_payload = await invalid.text()
        assert "must-not-echo" not in invalid_payload

        missing_target = await client.post(
            f"{server.origin}/api/actions/cron.run",
            headers=mutation_headers,
            json={"name": "api-key-that-must-not-echo"},
        )
        assert missing_target.status == 400
        assert "api-key-that-must-not-echo" not in await missing_target.text()

        created = await client.post(
            f"{server.origin}/api/actions/autopilot.enqueue",
            headers=mutation_headers,
            json={"title": "Browser task", "body": "Review resource screens"},
        )
        assert created.status == 200
        assert (await created.json())["resource"]["status"] == "queued"

        autopilot = await client.get(f"{server.origin}/api/autopilot", headers=headers)
        assert autopilot.status == 200
        assert (await autopilot.json())["data"]["initialized"] is True


def test_cli_rejects_remote_web_binding_before_launch():
    result = CliRunner().invoke(app, ["web", "--host", "0.0.0.0", "--no-open"])

    assert result.exit_code == 2
    assert "local-only" in result.output
