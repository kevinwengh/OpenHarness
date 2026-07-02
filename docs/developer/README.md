# Developer guide index

Use this directory as the guided layer over the repository's canonical architecture, extension,
and testing references.

## Suggested learning tracks

### First contribution

1. [Developer onboarding](ONBOARDING.md)
2. [Codebase guide](CODEBASE_GUIDE.md)
3. [Testing and validation](../TESTING.md)
4. The owning source module and its nearest tests

### Agent runtime or tool-loop work

1. [Architecture: main runtime flows](../ARCHITECTURE.md#main-runtime-flows)
2. [Codebase guide: interactive request path](CODEBASE_GUIDE.md#interactive-request-path)
3. `src/openharness/ui/runtime.py`
4. `src/openharness/engine/query_engine.py` and `src/openharness/engine/query.py`
5. `tests/test_ui/`, `tests/test_engine/`, and affected safety subsystem tests

### Provider or authentication work

1. [Codebase guide: provider and authentication path](CODEBASE_GUIDE.md#provider-and-authentication-path)
2. [Extending: provider](../EXTENDING.md#add-or-modify-a-provider)
3. `.claude/skills/openharness-add-provider/SKILL.md`

### Tools and extensions

1. [Extending OpenHarness](../EXTENDING.md)
2. [Codebase guide: tool execution and safety](CODEBASE_GUIDE.md#tool-execution-and-safety-path)
3. `.claude/skills/openharness-add-tool/SKILL.md` for tool changes

### Terminal UI or dashboard work

1. [Development: Python/TypeScript UI protocol](../DEVELOPMENT.md#pythontypescript-ui-protocol)
2. [Testing: test selection matrix](../TESTING.md#test-selection-matrix)
3. `src/openharness/ui/` with `frontend/terminal/`, or `src/openharness/autopilot/` with
   `autopilot-dashboard/`

### `ohmo` work

1. [Codebase guide: OpenHarness and ohmo boundary](CODEBASE_GUIDE.md#openharness-and-ohmo-boundary)
2. `ohmo/runtime.py`, `ohmo/gateway/`, and `ohmo/workspace.py`
3. `tests/test_ohmo/` plus affected core tests

## Planning work

The [improvement backlog](IMPROVEMENTS.md) records evidence-backed technical opportunities. It is
not a promise that every item should be implemented immediately. Re-check the cited source and
tests, define a narrow contract, and agree on scope before starting a cross-cutting refactor.
