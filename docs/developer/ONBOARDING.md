# Developer onboarding

This guide gets a new contributor from clone to a well-scoped first change. It assumes familiarity
with Python and Git; Node.js is only required for either TypeScript frontend.

## Suggested first 90 minutes

| Time | Outcome |
| --- | --- |
| 0–15 minutes | Install dependencies, run `oh --help`, and isolate local state |
| 15–35 minutes | Read the architecture system view and trace one request through the core files |
| 35–55 minutes | Run one focused test directory and locate the matching source owner |
| 55–90 minutes | Choose a bounded issue, write down its invariant/impact set, and prepare a focused test |

## What you are joining

The repository contains two related products:

- `openharness` (`oh` / `openh`) is the reusable coding-agent runtime, CLI, and terminal UI.
- `ohmo` is a personal-agent application built with OpenHarness. It adds a workspace, persistent
  personal memory, channel gateways, and conversation-scoped runtime management.

The model call is only one part of a request. Runtime composition resolves configuration and auth,
loads extensions, registers tools, applies permissions and hooks, streams events, and persists the
session. Read [the architecture overview](../ARCHITECTURE.md#system-view) before changing any of
those seams.

## 1. Prepare a local environment

Required for Python-only work:

- Python 3.10 or 3.11
- `uv`
- Git and `rg` (ripgrep)

Required only for the terminal UI or dashboard:

- Node.js 20
- npm

Optional components need their own environment: Docker for Docker-sandbox work, and tmux or iTerm2
for the matching swarm backend.

```bash
git clone https://github.com/HKUDS/OpenHarness.git
cd OpenHarness
uv sync --extra dev
uv run oh --help
```

Keep manual development state separate from a normal installation:

```bash
export OPENHARNESS_DEV_STATE="${TMPDIR:-/tmp}/openharness-dev"
export OPENHARNESS_CONFIG_DIR="$OPENHARNESS_DEV_STATE/config"
export OPENHARNESS_DATA_DIR="$OPENHARNESS_DEV_STATE/data"
export OPENHARNESS_LOGS_DIR="$OPENHARNESS_DEV_STATE/logs"
uv run oh --dry-run --output-format json
```

The dry run may report missing authentication; that is useful configuration evidence and does not
make a model request. Never point these variables at a normal personal installation while testing
state migrations. Do not commit credentials, sessions, or personal workspace content.

For terminal UI work:

```bash
cd frontend/terminal
npm ci
npx tsc --noEmit
```

For dashboard work:

```bash
cd autopilot-dashboard
npm ci
npm run build
```

## 2. Establish a baseline

Run a narrow offline check before editing so failures introduced by the change can be distinguished
from environment or branch failures:

```bash
uv run pytest -q tests/test_engine
uv run ruff check src tests scripts
```

Choose a test directory related to the intended change instead of `tests/test_engine` when
appropriate. The complete mapping is in [Testing and validation](../TESTING.md#test-selection-matrix).
Normal tests must not need credentials or network access.

## 3. Build the mental model

Read source in this order for a representative request:

1. `src/openharness/cli.py` — command-line selection and launch modes.
2. `src/openharness/ui/runtime.py` — composition root; look at `build_runtime()`, `handle_line()`,
   and cleanup.
3. `src/openharness/engine/query_engine.py` — conversation state and submission boundary.
4. `src/openharness/engine/query.py` — streaming model/tool loop.
5. `src/openharness/tools/base.py` and `src/openharness/permissions/checker.py` — executable
   capability and safety contracts.
6. `src/openharness/engine/stream_events.py` — events consumed by UIs and gateways.
7. The nearest test for the subsystem you plan to change.

Then use the [codebase guide](CODEBASE_GUIDE.md) to branch into providers, persistence, extensions,
tasks/swarm, frontends, or `ohmo`. For a line-by-line lifecycle rather than a repository map, choose
the matching document from [Critical runtime flows](flows/README.md).

## 4. Choose a first contribution

A good first change has one owner, one observable contract, and a focused test. Examples include:

- improve an error message in one provider client and assert the normalized error;
- fix a tool edge case and cover its schema, result, and read-only classification;
- add a missing deterministic test for a command or configuration precedence rule;
- correct documentation after verifying the owning source and test;
- isolate a small helper from a large module without changing public behavior.

Avoid beginning with a rewrite of `cli.py`, `commands/registry.py`, `ui/runtime.py`, or
`engine/query.py`. They are cross-subsystem seams; even a small behavioral change there can require
permissions, hooks, persistence, stream-event, and UI validation.

## 5. Use the contribution loop

1. Read `AGENTS.md`, the owning source, and the nearest tests.
2. State the intended behavior and the boundaries that must remain unchanged.
3. Add or update a focused test when behavior changes.
4. Implement at the narrowest owning module.
5. Run the focused test, then the affected test directories.
6. Run Ruff on touched Python paths; run TypeScript/build checks when a frontend boundary changed.
7. Update the owning document and `CHANGELOG.md` for user-visible behavior.
8. Review the diff for generated state, credentials, or unrelated edits.

Repository-local workflows under `.claude/skills/` provide extra checklists for general
OpenHarness development, tools, providers, and opt-in live model evaluation.

## 6. Know the invariants

Treat these as review blockers unless the change explicitly and safely revises the contract:

- Credential and other sensitive paths remain denied even in full-auto mode.
- Project plugins remain disabled unless `allow_project_plugins` is explicitly enabled.
- Tools stay asynchronous, validate arguments with Pydantic, return `ToolResult`, and only claim
  read-only status when the full invocation is read-only.
- Provider changes cover auth resolution, request conversion, streaming, tool-call replay, usage,
  and errors—not only the provider display name.
- Agent-loop changes preserve permission checks, hook ordering, sandbox routing, persisted
  continuation metadata, stream events, and cleanup.
- Reusable behavior belongs in `src/openharness`; personal workspace and gateway behavior belongs
  in `ohmo`.
- Tests remain deterministic and offline unless a live evaluation is explicitly requested.

## 7. Get unstuck quickly

| Symptom | First places to inspect |
| --- | --- |
| Provider is listed but requests fail | `config/settings.py`, `auth/`, `api/registry.py`, selected client, provider tests |
| Tool is missing | `tools/__init__.py`, plugin loader, MCP manager, runtime registry construction |
| Tool is unexpectedly denied/allowed | `permissions/checker.py`, tool `is_read_only()`, hook definitions, query loop |
| UI output differs from engine state | `engine/stream_events.py`, `ui/backend_host.py`, `frontend/terminal/src/types.ts` |
| Session cannot resume | session backend/storage, message sanitization, tool metadata, resume tests |
| `ohmo` replies or routing are wrong | `ohmo/gateway/router.py`, runtime pool, bridge, channel adapter, `tests/test_ohmo/` |
| Async task/swarm work hangs | task manager, subprocess backend, mailbox/coordinator state, cleanup tests |

## First-change completion checklist

- [ ] I can explain which module owns the behavior.
- [ ] I read the owning source and nearest tests before editing.
- [ ] My test demonstrates the contract or regression.
- [ ] I tested denial, error, or cleanup behavior when relevant.
- [ ] I ran the checks selected from `docs/TESTING.md`.
- [ ] I updated docs and changelog where the observable behavior changed.
- [ ] My diff contains no credentials, generated sessions, or unrelated local files.
