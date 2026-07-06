# Development guide

This guide is for maintainers changing OpenHarness itself. For user installation and configuration,
start with the root README. New contributors should follow the time-boxed
[developer onboarding guide](developer/ONBOARDING.md), then use the
[codebase guide](developer/CODEBASE_GUIDE.md) to locate the owning subsystem. For editor launch
configurations and a source-built local installation, use the
[VS Code and local release guide](developer/VSCODE_LOCAL_DEVELOPMENT_AND_RELEASE.md).

## Prerequisites

- Python 3.10 or 3.11
- [`uv`](https://docs.astral.sh/uv/) for the repository's documented Python workflow
- Node.js 20 for terminal UI, web UI, or dashboard work
- Git and ripgrep
- Docker only for sandbox integration work
- tmux or iTerm2 only for the corresponding optional swarm backends

## Setup

```bash
git clone https://github.com/HKUDS/OpenHarness.git
cd OpenHarness
uv sync --extra dev
uv run oh --help
```

For terminal UI work:

```bash
cd frontend/terminal
npm ci
npx tsc --noEmit
```

For local web UI work:

```bash
cd frontend/web
npm ci
npm test
npx playwright install chromium  # first run only
npm run test:e2e
```

The E2E command builds the production bundle into `src/openharness/_web` before launching the
credential-free local Playwright fixture. Commit source and generated package assets together; CI
reruns component and rendered-browser checks, rebuilds the bundle, and fails when assets disagree.

For autopilot dashboard work:

```bash
cd autopilot-dashboard
npm ci
npm run build
```

Use `OPENHARNESS_CONFIG_DIR`, `OPENHARNESS_DATA_DIR`, and `OPENHARNESS_LOGS_DIR` to isolate manual test state from your normal installation.

## Repository map

| Path | Purpose |
| --- | --- |
| `src/openharness/api` | Provider clients, registry, streaming contracts, usage |
| `src/openharness/auth` | API/external subscription authentication and credential storage |
| `src/openharness/engine` | Message models, streamed events, agent loop, cost tracking |
| `src/openharness/ui` | Shared runtime assembly, Python backend protocol, React launcher, Textual UI |
| `src/openharness/tools` | Built-in tool contracts and implementations |
| `src/openharness/config` | Settings models, precedence, and filesystem paths |
| `src/openharness/permissions`, `sandbox` | Tool policy and isolated execution |
| `src/openharness/hooks`, `plugins`, `skills`, `mcp` | Extension systems |
| `src/openharness/memory`, `services` | Persistence, compaction support, cron, extraction, autodream |
| `src/openharness/tasks`, `swarm`, `coordinator` | Background work and multi-agent coordination |
| `src/openharness/channels`, `bridge` | Chat/event adapters and bridged sessions |
| `src/openharness/autopilot` | Repository work intake, policies, execution records, dashboard export |
| `ohmo` | Personal-agent product built on the OpenHarness runtime |
| `frontend/terminal` | React/Ink terminal UI packaged in the Python wheel |
| `frontend/web` | React/Vite local browser UI; builds packaged assets under `src/openharness/_web` |
| `autopilot-dashboard` | Vite source for the generated/published dashboard |
| `tests` | Offline unit and integration-style test suites mirroring subsystems |
| `scripts` | Installer and opt-in E2E/manual verification drivers |
| `.claude/skills` | Repository-local development workflows for coding agents |

See [ARCHITECTURE.md](ARCHITECTURE.md) for runtime flows and ownership.

## Change workflow

1. Locate the owning subsystem and its nearest tests.
2. Reproduce the current behavior with a narrow test or command.
3. Add or update a failing test when behavior changes.
4. Implement at the owning boundary.
5. Run the narrow test, then the relevant suite from [TESTING.md](TESTING.md).
6. Run Ruff and any affected TypeScript/build checks.
7. Update architecture, extension, configuration, or user docs when their claims changed.
8. Add an `Unreleased` changelog entry for user-visible changes.

## High-risk seams

### Agent loop

Changes in `engine/query.py` can affect permissions, hook ordering, sandbox execution, parallel tools, stream events, compaction, and message replay. Verify all touched seams explicitly; a passing happy-path engine test is insufficient for a broad loop change.

### Runtime composition

`ui/runtime.py` combines almost every subsystem. Keep it as orchestration, move new domain logic into its owning module, and test lifecycle cleanup for any new resource.

### Settings and profiles

Settings combine defaults, saved JSON, profiles, credentials, environment variables, and CLI overrides. Preserve precedence and do not print secrets. Use temporary config/data directories in tests.

### Provider compatibility

Provider work may require changes across registry metadata, settings profiles, auth, client selection, streamed-response parsing, assistant tool-call replay, setup UX, dry-run diagnostics, and tests. Use the `openharness-add-provider` skill.

### Python/TypeScript UI protocol

When changing messages between `ui/backend_host.py` and `frontend/terminal`, update both sides and tests. The terminal source is force-included in the wheel by `pyproject.toml`.

### ohmo versus core

Put reusable agent behavior in `src/openharness`. Put personal workspace, gateway, and channel-specific session behavior in `ohmo`. Avoid importing `ohmo` from core runtime modules.

## Style and design conventions

- Use type hints and Pydantic models at input/config boundaries.
- Prefer small modules with a protocol or dataclass boundary over new global mutable state.
- Use async APIs for model, tool, channel, and process operations.
- Normalize user-visible failures into actionable messages; preserve exceptions for programmer errors and tests.
- Use atomic writes and file locks for shared persisted state.
- Keep security defaults conservative: project code is untrusted, credential paths remain inaccessible, and network targets are validated.
- Do not add model/network dependencies to the default pytest suite.

## Useful local commands

```bash
# Run one subsystem
uv run pytest -q tests/test_engine

# Run one test while iterating
uv run pytest -q tests/test_tools/test_core_tools.py -k file_read

# Inspect CLI composition without a model call
uv run oh --dry-run --output-format json

# Run all Python checks used by CI
uv run ruff check src tests scripts
uv run pytest -q
```

## Release-sensitive files

When cutting a release, keep the version in `pyproject.toml`, `src/openharness/cli.py`, changelog/release notes, and user-facing documentation consistent. Build artifacts and publication steps are not currently defined in a checked-in release workflow, so confirm the maintainer's current publishing procedure before uploading anything.
