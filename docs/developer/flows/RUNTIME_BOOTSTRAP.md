# Runtime bootstrap and shutdown

## Question answered

What does OpenHarness construct before the first model call, who owns those objects, and how are
they cleaned up?

`src/openharness/ui/runtime.py::build_runtime()` is the composition root. It turns configuration and
application overrides into a `RuntimeBundle` used by CLI, React backend, print mode, workers, and
`ohmo`.

## Construction sequence

```text
CLI / backend / ohmo arguments
        │
        ▼
load settings + merge explicit overrides
        │
        ├─ discover enabled plugins
        ├─ resolve auth and provider client
        ├─ merge/connect MCP servers
        ├─ build built-in + MCP + plugin tool registry
        ├─ construct app-state snapshot
        ├─ load hooks and create HookExecutor
        ├─ assemble system prompt (skills, instructions, memory)
        ├─ initialize session/tool carry-over metadata
        ├─ create QueryEngine
        ├─ restore/sanitize saved messages, if supplied
        ├─ start Docker sandbox, if configured
        └─ create command registry and RuntimeBundle
```

## 1. Settings and overrides

`build_runtime()` calls `load_settings().merge_cli_overrides(...)`. The explicit inputs include
model, max turns, effort, base URL, custom system prompt, API key, API format, active profile, and
permission mode. The original override dictionary is retained on `RuntimeBundle` so later slash
commands can reload disk settings without losing process-scoped CLI choices.

The working directory and extra skill/plugin roots are expanded and resolved early. That normalized
`cwd` becomes the base for prompt context, permission paths, tools, sessions, and application state.

## 2. Provider client selection

If the caller injects an `api_client` (mainly tests/embedding), it is used directly. Otherwise
`_resolve_api_client_from_settings()` materializes the active profile, resolves authentication, and
selects one of:

- `CopilotClient` for the Copilot API format;
- `CodexApiClient` for a Codex subscription profile;
- OAuth-configured `AnthropicApiClient` for Claude subscription auth;
- `OpenAICompatibleClient` for OpenAI-compatible formats;
- API-key `AnthropicApiClient` as the default path.

This is why provider work cannot stop at registry labels: settings, auth, and client construction all
participate before any request conversion occurs.

## 3. Extensions, MCP, and tools

Enabled plugins are discovered before MCP and tool construction. Settings MCP definitions and
plugin MCP definitions are merged into `McpClientManager`, and `connect_all()` runs during bootstrap.
Connection failures become per-server failed statuses rather than aborting every runtime.

`create_default_tool_registry(mcp_manager)` registers built-ins, MCP resource tools, and an adapter
for each connected MCP tool. Enabled plugin Python tools are registered afterward. Since
`ToolRegistry.register()` assigns by name, a later tool with the same name replaces an earlier entry;
name collisions therefore affect behavior and must be reviewed intentionally.

## 4. Hooks, prompt, and engine

The runtime creates a `HookExecutor` with the current hook registry, working directory, provider
client, and default model. It then calls `build_runtime_system_prompt()` with settings, cwd, initial
prompt, extension roots, and project-memory policy.

The resulting `QueryEngine` receives:

- provider client and model settings;
- tool registry and permission checker;
- system prompt and context/compaction limits;
- permission/question callbacks supplied by the selected UI;
- hook executor;
- runtime-only metadata such as MCP manager, bridge manager, session ID, edit approval callback,
  extension roots, image/vision configuration, and continuation checkpoints.

Saved messages are Pydantic-validated and sanitized before `engine.load_messages()`. Persisted tool
metadata overlays safe defaults, preserving continuation state without serializing live managers or
callbacks.

## 5. RuntimeBundle ownership

`RuntimeBundle` is the session-scoped ownership container:

| Field | Responsibility |
| --- | --- |
| `api_client` | Provider streaming transport |
| `mcp_manager` | MCP sessions, tools, resources, and statuses |
| `tool_registry` | Model-callable built-in, MCP, and plugin tools |
| `hook_executor` | Lifecycle and tool policy/observation hooks |
| `engine` | Conversation history, usage, and model/tool loop |
| `commands` | Slash command lookup and handlers |
| `app_state` | UI-facing resolved state snapshot |
| `session_backend` | Persistence implementation, replaceable by `ohmo` |
| extension/memory fields | Application-specific discovery and memory behavior |

`start_runtime()` fires `session_start` hooks after construction. Callers are responsible for
calling it; `build_runtime()` alone does not fire the hook.

## 6. Per-prompt refresh versus full rebuild

Before a normal line, `handle_line()` can reload hooks, rebuild the system prompt for the latest
user text, and synchronize app state without reconstructing every resource. Commands that change the
provider/client set `refresh_runtime`, which triggers client/settings refresh; `ohmo` may close and
rebuild its entire bundle to preserve application-specific state.

## 7. Shutdown order

`close_runtime()` performs best-effort and owned-resource cleanup:

1. Stop the shared Docker sandbox session.
2. Extract local personalization rules from the conversation, without blocking shutdown on failure.
3. Close all MCP sessions/transport stacks.
4. Fire the `session_end` hook.
5. Close the API client when it exposes an asynchronous `close()` method.

Every caller that builds a runtime must use `try/finally` or an equivalent lifecycle so this path
runs. Background task-manager cleanup is owned separately by its singleton lifecycle.

## Failure boundaries

- Missing provider auth prints profile-specific guidance and exits before engine construction.
- A failed MCP server is recorded in status; connected servers still contribute tools.
- Malformed/disabled plugins are skipped according to loader rules.
- Docker startup may fail runtime construction when explicitly required.
- Failures during personalization extraction are suppressed; MCP/API cleanup still proceeds.

## Where to change behavior

Add domain behavior to its subsystem and keep `runtime.py` as orchestration. New resource types must
define construction, injection, refresh behavior, and cleanup. Any new tool-loop state must be
classified as live runtime-only metadata or JSON-safe persisted continuation metadata.

## Verification map

- `tests/test_ui/test_runtime_api_key.py`: auth/client construction failures.
- `tests/test_ui/test_runtime_close.py`: API-client cleanup.
- `tests/test_ui/test_runtime_plugin_tools.py`: plugin tool registration.
- `tests/test_ui/test_project_plugin_security.py`: project plugin trust boundary.
- `tests/test_ui/test_runtime_plan_mode.py`: runtime prompt/permission refresh.
- `tests/test_mcp/` and `tests/test_plugins/`: connected extension lifecycles.
