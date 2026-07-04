# Developer guide index

Use this directory as the guided layer over the repository's canonical architecture, extension,
and testing references.

## Suggested learning tracks

For source-level lifecycle traces, use the [critical runtime flows](flows/README.md). Each flow is a
standalone answer to a common “how does this actually work?” question and links to its owning tests.

### First contribution

1. [Developer onboarding](ONBOARDING.md)
2. [Codebase guide](CODEBASE_GUIDE.md)
3. [Testing and validation](../TESTING.md)
4. The owning source module and its nearest tests

### Agent runtime or tool-loop work

1. [Prompt, memory, tools, and compaction end to end](flows/PROMPT_MEMORY_TOOLS_COMPACTION_E2E.md),
   then the shorter [prompt/tool loop](flows/PROMPT_TOOL_LOOP.md)
2. [Tool governance](flows/TOOL_GOVERNANCE.md) for permissions, hooks, and sandboxing
3. [Architecture: main runtime flows](../ARCHITECTURE.md#main-runtime-flows)
4. `src/openharness/ui/runtime.py`, `src/openharness/engine/query_engine.py`, and
   `src/openharness/engine/query.py`
5. `tests/test_ui/`, `tests/test_engine/`, and affected safety subsystem tests

### Provider or authentication work

1. [Provider integration index](providers/README.md) to map profiles and registry names to the
   Anthropic, OpenAI-compatible, Codex subscription, or GitHub Copilot runtime client
2. The matching detailed client guide for authentication, request conversion, streaming, tool
   replay, retries, capability boundaries, tests, and known gaps
3. [Codebase guide: provider and authentication path](CODEBASE_GUIDE.md#provider-and-authentication-path)
4. [Extending: provider](../EXTENDING.md#add-or-modify-a-provider)
5. `.claude/skills/openharness-add-provider/SKILL.md`

### Tools and extensions

1. [Extending OpenHarness](../EXTENDING.md)
2. [Tool governance](flows/TOOL_GOVERNANCE.md), [MCP integration](flows/MCP_INTEGRATION.md), or
   [extension discovery](flows/EXTENSION_DISCOVERY.md)
3. [Codebase guide: tool execution and safety](CODEBASE_GUIDE.md#tool-execution-and-safety-path)
4. `.claude/skills/openharness-add-tool/SKILL.md` for tool changes

### Terminal UI or dashboard work

1. [Interactive `uv run oh` frontend/backend flow](flows/INTERACTIVE_OH_FRONTEND_BACKEND_E2E.md),
   then the shorter [terminal UI protocol](flows/TERMINAL_UI_PROTOCOL.md)
2. [Development: Python/TypeScript UI protocol](../DEVELOPMENT.md#pythontypescript-ui-protocol)
3. [Testing: test selection matrix](../TESTING.md#test-selection-matrix)
4. `src/openharness/ui/` with `frontend/terminal/`, or `src/openharness/autopilot/` with
   `autopilot-dashboard/`

### `ohmo` work

1. [`ohmo` developer reference](ohmo/README.md) for dedicated source-level guides to workspace,
   local runtime, memory, persistence, gateway, routing, runtime pooling, media, and groups
2. The shorter [`ohmo` integration flow](flows/OHMO_INTEGRATION.md)
3. [Codebase guide: OpenHarness and ohmo boundary](CODEBASE_GUIDE.md#openharness-and-ohmo-boundary)
4. `ohmo/runtime.py`, `ohmo/gateway/`, and `ohmo/workspace.py`
5. `tests/test_ohmo/` plus affected core tests

### Memory, sessions, or background agents

1. [Prompt, memory, tools, and compaction end to end](flows/PROMPT_MEMORY_TOOLS_COMPACTION_E2E.md),
   [memory, sessions, and compaction](flows/MEMORY_SESSION_COMPACTION.md), or
   [background agents](flows/BACKGROUND_AGENTS.md)
2. The owning `memory/`, `services/`, `tasks/`, or `swarm/` source and tests
3. The [prompt/tool loop](flows/PROMPT_TOOL_LOOP.md) where state enters or leaves a model turn

## Planning work

The [improvement backlog](IMPROVEMENTS.md) records evidence-backed technical opportunities. It is
not a promise that every item should be implemented immediately. Re-check the cited source and
tests, define a narrow contract, and agree on scope before starting a cross-cutting refactor.
