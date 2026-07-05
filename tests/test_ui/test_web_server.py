"""Contracts for the secure local web UI host and redacted bootstrap."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from typer.testing import CliRunner

from openharness.cli import app
from openharness.config.settings import ProviderProfile, Settings
from openharness.ui.web_models import build_web_bootstrap
from openharness.ui.web_server import (
    WebServerConfig,
    WebServerConfigurationError,
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


def test_cli_rejects_remote_web_binding_before_launch():
    result = CliRunner().invoke(app, ["web", "--host", "0.0.0.0", "--no-open"])

    assert result.exit_code == 2
    assert "local-only" in result.output
