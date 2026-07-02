# Codebase guide

This guide answers two contributor questions: “where does this behavior live?” and “what else can a
change here affect?” It describes commit `9b2efd7`; source and tests remain authoritative as the
repository evolves.

## Repository topology

```text
OpenHarness/
├── src/openharness/       reusable runtime and the openharness/oh/openh applications
│   ├── api, auth, config  provider requests, credentials, profiles, settings
│   ├── engine             conversation models, events, accounting, model/tool loop
│   ├── tools              built-in executable capabilities and registry
│   ├── permissions        tool authorization policy
│   ├── sandbox            sandbox-runtime and Docker routing
│   ├── hooks, skills,
│   │   plugins, mcp       extension and instruction systems
│   ├── services, memory   sessions, compaction, cron, extraction, durable memory
│   ├── tasks, swarm,
│   │   coordinator        background and multi-agent work
│   ├── channels, bridge   chat transports, bus, and bridged sessions
│   ├── autopilot          repository work intake, policy, execution, export
│   └── ui                 runtime composition and terminal backends
├── ohmo/                  personal workspace and gateway application
├── frontend/terminal/     React/Ink terminal UI packaged in the Python wheel
├── autopilot-dashboard/   Vite dashboard source
├── tests/                 offline tests organized mostly by source subsystem
├── scripts/               installers and opt-in/manual E2E drivers
├── docs/                  maintained references and generated dashboard output
└── .claude/skills/        repository-local contributor/agent workflows
```

## Interactive request path

```text
CLI / React TUI / Textual TUI
        │
        ▼
ui.runtime.build_runtime()
  settings → auth/client → plugins/MCP → tools → permissions/hooks → prompt → session
        │
        ▼
QueryEngine.submit_message()
  append user message → create QueryContext
        │
        ▼
engine.query.run_query()
  stream provider response → emit events → execute requested tools → replay results
        │                                      │
        │                                      ├─ permission checker
        │                                      ├─ pre/post hooks
        │                                      ├─ host or sandbox execution
        │                                      └─ normalized ToolResult
        ▼
persist messages/metadata/usage → optional memory work → render output → cleanup
```

Key reading points:

| Boundary | Primary source | Contract to preserve | Representative tests |
| --- | --- | --- | --- |
| CLI launch | `src/openharness/cli.py` | CLI overrides, mode selection, actionable failures | `tests/test_entrypoints/`, command/config tests |
| Runtime assembly | `src/openharness/ui/runtime.py` | Resource construction/cleanup and dependency wiring | `tests/test_ui/test_runtime_*` |
| Conversation owner | `src/openharness/engine/query_engine.py` | Message order, usage, submission, persistence hooks | `tests/test_engine/test_query_engine.py` |
| Tool loop | `src/openharness/engine/query.py` | Streaming, tool replay, max turns, safety lifecycle | `tests/test_engine/` plus permissions/hooks/tools |
| Output protocol | `src/openharness/engine/stream_events.py` | Stable event meaning across renderers | engine/UI/ohmo gateway tests |

## Tool execution and safety path

Tools implement the contract in `tools/base.py`: a Pydantic input model, asynchronous `execute()`,
a normalized `ToolResult`, and invocation-specific read-only classification. Built-ins are assembled
by `create_default_tool_registry()`; plugin and MCP tools join during runtime composition.

For every requested tool call, the engine resolves the registered name, validates arguments, asks
the permission checker, runs pre-tool hooks, routes supported work through the selected sandbox,
executes the tool, runs post-tool hooks, emits events, and gives the result back to the provider.
Unknown tools and execution failures become recoverable tool results rather than arbitrary dispatch.

When changing this path, inspect all of:

- `src/openharness/tools/` and `tests/test_tools/`;
- `src/openharness/permissions/` and `tests/test_permissions/`;
- `src/openharness/hooks/` and `tests/test_hooks/`;
- `src/openharness/sandbox/` and `tests/test_sandbox/`;
- tool execution and replay cases in `tests/test_engine/`.

Sensitive-path denial is stronger than normal configurable allow rules, and project plugin execution
is opt-in. Do not treat full-auto mode as permission to weaken either trust boundary.

## Provider and authentication path

A provider label is not the runtime contract. Trace the complete path:

1. `api/registry.py` identifies provider/profile metadata and model defaults.
2. `config/settings.py` merges defaults, saved settings/profiles, environment values, and explicit
   overrides.
3. `auth/` resolves API keys or external subscription credentials without exposing secrets.
4. `ui/runtime.py` selects and constructs the streaming client.
5. `api/client.py`, `openai_client.py`, `codex_client.py`, or `copilot_client.py` converts messages,
   tools, token settings, and streamed responses.
6. The engine replays assistant tool calls and user tool results on later turns.

Provider validation therefore needs registry, config/auth, request/stream conversion, error, usage,
and multi-turn replay coverage. Start with `.claude/skills/openharness-add-provider/SKILL.md`.

## Extension assembly path

Runtime construction loads extension sources before finalizing the prompt and registry:

- Skills: bundled, user compatibility roots, explicit roots, project roots, then enabled plugins.
  Later definitions with the same name win.
- Plugins: user plugins load from the user plugin root. Project plugins require
  `allow_project_plugins` because Python tools and hooks can execute code.
- MCP: settings and plugin declarations create stdio, HTTP, or WebSocket connections; adapted tools
  use the normal permission and tool lifecycle.
- Hooks: lifecycle and tool hooks are ordered by priority and registration order.
- Commands: built-ins, plugins, and user-invocable skills are exposed through the command registry.

See [Extending OpenHarness](../EXTENDING.md) for concrete implementation checklists.

## Persistence and long-running work

| Concern | Owner | Important interactions |
| --- | --- | --- |
| Conversation sessions | `services/session_backend.py`, `session_storage.py` | Message sanitization, tool metadata, resume/export |
| Compaction | `services/compact/`, engine integration | Context limits, image/tool payloads, task focus state |
| Project memory | `memory/` | Scanning, schema/migration, prompt injection |
| Personalization/autodream | `personalization/`, `services/autodream/` | Post-turn/session extraction and cleanup |
| Background tasks | `tasks/` | Subprocess lifecycle, bounded output, cancellation |
| Multi-agent state | `swarm/`, `coordinator/` | Mailboxes, permissions, worktrees, continuation |
| Cron | `services/cron.py`, `cron_scheduler.py` | Registry, process execution, history, notification |
| Autopilot | `autopilot/` | Repository state, policies, journals, verification, dashboard export |

Use temporary config/data/log roots in tests. Persist JSON-safe continuation data, use the existing
atomic-write and file-lock helpers, and exercise corrupt/legacy input when changing a stored format.

## Python and TypeScript UI boundary

`src/openharness/ui/backend_host.py` translates runtime events and interactive requests into the
line-oriented protocol consumed by `frontend/terminal/src/`. The frontend source is force-included
in the Python wheel by `pyproject.toml`, so protocol, launcher, packaging, and frontend type changes
form one release boundary.

Change both sides together. At minimum run UI Python tests and `npx tsc --noEmit`; use the targeted
interactive drivers listed in [Testing and validation](../TESTING.md#live-and-manual-evaluation) for
input/rendering behavior that a typecheck cannot demonstrate.

The autopilot dashboard has a different boundary: `src/openharness/autopilot/` exports state and
`autopilot-dashboard/` builds published files under `docs/autopilot/`.

## OpenHarness and ohmo boundary

The intended dependency direction is `ohmo` → `openharness`: `ohmo` composes the reusable engine,
channels, commands, prompts, session contract, and terminal runtime with a personal workspace and
gateway. A conversation key maps to a runtime in `ohmo/gateway/runtime.py`; the bridge converts
channel events and runtime progress into outbound channel messages.

Current source has a few optional reverse imports from core into `ohmo` for workspace attachment
paths, managed Feishu groups, and cron notification/config behavior. These are existing integration
shortcuts, not a general invitation to add more reverse dependencies. New reusable contracts belong
in core and application-specific adapters belong in `ohmo`; see the first item in the
[improvement backlog](IMPROVEMENTS.md).

## Change-impact map

| If you change | Also inspect |
| --- | --- |
| `engine/query.py` | permissions, hooks, sandbox, stream events, compaction, session continuation |
| `ui/runtime.py` | client/auth selection, plugins/MCP, prompt, resource cleanup, all UI entrypoints |
| settings/profile fields | environment and CLI precedence, serialization, redaction, setup/dry-run UX |
| conversation message shapes | every provider converter, persistence sanitizer, compaction, UI/gateway |
| tool schema/result metadata | provider schema conversion, permission path extraction, persistence, UI |
| channel event shapes | bus, adapter implementations, bridge, `ohmo` gateway, authorization tests |
| frontend protocol | Python backend host, TypeScript types/handlers, package inclusion, UI tests |
| persisted formats | legacy/corrupt input, migration/defaults, atomic writes, resume/export |
| task/swarm process launch | shell portability, cancellation, output draining, mailbox/worktree cleanup |

## Fast source-discovery recipes

```bash
# Find a symbol and all likely call sites
rg -n 'build_runtime|run_query' src ohmo tests

# Find the tests nearest a subsystem
rg --files tests/test_engine tests/test_ui

# Trace a settings field across config, runtime, and tests
rg -n 'allow_project_plugins' src ohmo tests

# Find cross-product imports before moving a boundary
rg -n 'from ohmo|import ohmo' src/openharness
rg -n 'from openharness|import openharness' ohmo

# Inspect the exact CI baseline
sed -n '1,240p' .github/workflows/ci.yml
```

Use [Testing and validation](../TESTING.md) to turn the discovered impact set into focused and
broader checks.
