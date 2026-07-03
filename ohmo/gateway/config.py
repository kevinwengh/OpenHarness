"""Config IO for ohmo gateway.

Integration: This ohmo module specializes the reusable OpenHarness runtime with personal
workspace, memory, session, gateway, or channel behavior; core modules must not depend on it.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve the ohmo workspace boundary, conversation/session isolation, attachment
and channel contracts, credential redaction, and cleanup of per-session runtimes.
"""

from __future__ import annotations

from pathlib import Path

from openharness.config.schema import Config

from ohmo.gateway.models import GatewayConfig
from ohmo.workspace import get_gateway_config_path


def load_gateway_config(workspace: str | Path | None = None) -> GatewayConfig:
    """Load ``.ohmo/gateway.json``.

    Integration: Called by ``_prompt_provider_profile``, ``_run_gateway_config_wizard`` and
    collaborates with ``get_gateway_config_path``, ``path.exists``, ``GatewayConfig``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    path = get_gateway_config_path(workspace)
    if path.exists():
        return GatewayConfig.model_validate_json(path.read_text(encoding="utf-8"))
    return GatewayConfig()


def save_gateway_config(config: GatewayConfig, workspace: str | Path | None = None) -> Path:
    """Persist ``.ohmo/gateway.json``.

    Integration: Called by ``_run_gateway_config_wizard``, ``handle_gateway_provider_command``
    and collaborates with ``get_gateway_config_path``, ``path.parent.mkdir``,
    ``path.write_text``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    path = get_gateway_config_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def build_channel_manager_config(config: GatewayConfig) -> Config:
    """Project gateway settings into the channel compatibility models.

    Integration: Called by ``OhmoGatewayService.__init__`` and collaborates with ``Config``,
    ``model_copy``, ``config.channel_configs.get``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    root = Config()
    root.channels.send_progress = config.send_progress
    root.channels.send_tool_hints = config.send_tool_hints
    for name in config.enabled_channels:
        if not hasattr(root.channels, name):
            continue
        channel_config = getattr(root.channels, name).model_copy(
            update={"enabled": True, **config.channel_configs.get(name, {})}
        )
        setattr(root.channels, name, channel_config)
    return root
