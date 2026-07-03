"""Tool for updating MCP auth configuration.

Integration: This module participates in model-callable tools registered with the shared engine
governance path.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve Pydantic schemas, async ToolResult behavior, read-only policy,
context.cwd, hooks, sandboxing, output bounds, and registration.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from openharness.config.settings import load_settings, save_settings
from openharness.mcp.types import McpHttpServerConfig, McpStdioServerConfig, McpWebSocketServerConfig
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class McpAuthToolInput(BaseModel):
    """Arguments for MCP auth updates.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    server_name: str = Field(description="Configured MCP server name")
    mode: str = Field(description="Auth mode: bearer, header, or env")
    value: str = Field(description="Secret value to persist")
    key: str | None = Field(default=None, description="Header or env key override")


class McpAuthTool(BaseTool):
    """Persist MCP auth settings for one server.

    Integration: Constructed or referenced by ``create_default_tool_registry``.

    Event loop: Async methods ``execute`` run on their caller's loop; instances must retain
    clear task, cancellation, and cleanup ownership.

    Change safety: Keep the input schema, read-only classification, async ``ToolResult``
    contract, permission metadata, hooks, sandbox behavior, and registration synchronized.
    """

    name = "mcp_auth"
    description = "Configure auth for an MCP server and reconnect active sessions when possible."
    input_model = McpAuthToolInput

    async def execute(self, arguments: McpAuthToolInput, context: ToolExecutionContext) -> ToolResult:
        """Execute one model-requested ``McpAuthTool`` invocation.

        Integration: Exposed through ``McpAuthTool`` and collaborates with ``load_settings``,
        ``save_settings``, ``ToolResult``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the asynchronous ``ToolResult`` contract, ``context.cwd``, and
        normalized operational failures; preserve permission, hook, sandbox, metadata, and
        output-size assumptions; preserve exception and fallback behavior expected by callers.

        Tool contract: The engine validates the Pydantic input and applies hooks and permission
        policy before awaiting this method. Return ``ToolResult`` for expected operational
        failures, resolve paths from ``context.cwd``, keep output and metadata serializable and
        bounded, and do not block the event loop. Revisit sandbox routing, secret redaction,
        tool-result replay, and registration whenever execution behavior changes.
        """
        settings = load_settings()
        mcp_manager = context.metadata.get("mcp_manager")
        config = settings.mcp_servers.get(arguments.server_name)
        if config is None and mcp_manager is not None:
            getter = getattr(mcp_manager, "get_server_config", None)
            if callable(getter):
                config = getter(arguments.server_name)
        if config is None:
            return ToolResult(output=f"Unknown MCP server: {arguments.server_name}", is_error=True)

        if isinstance(config, McpStdioServerConfig):
            if arguments.mode not in {"env", "bearer"}:
                return ToolResult(output="stdio MCP auth supports env or bearer modes", is_error=True)
            env_key = arguments.key or "MCP_AUTH_TOKEN"
            env = dict(config.env or {})
            env[env_key] = f"Bearer {arguments.value}" if arguments.mode == "bearer" else arguments.value
            updated = config.model_copy(update={"env": env})
        elif isinstance(config, (McpHttpServerConfig, McpWebSocketServerConfig)):
            if arguments.mode not in {"header", "bearer"}:
                return ToolResult(output="http/ws MCP auth supports header or bearer modes", is_error=True)
            header_key = arguments.key or "Authorization"
            headers = dict(config.headers)
            headers[header_key] = (
                f"Bearer {arguments.value}" if arguments.mode == "bearer" and header_key == "Authorization" else arguments.value
            )
            updated = config.model_copy(update={"headers": headers})
        else:
            return ToolResult(output="Unsupported MCP server config type", is_error=True)

        settings.mcp_servers[arguments.server_name] = updated
        save_settings(settings)

        if mcp_manager is not None:
            try:
                mcp_manager.update_server_config(arguments.server_name, updated)
                await mcp_manager.reconnect_all()
            except Exception as exc:  # pragma: no cover - defensive
                return ToolResult(
                    output=f"Saved MCP auth for {arguments.server_name}, but reconnect failed: {exc}",
                    is_error=True,
                )

        return ToolResult(output=f"Saved MCP auth for {arguments.server_name}")
