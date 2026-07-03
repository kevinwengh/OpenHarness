# Testing and validation

The test strategy has three layers: offline Python tests, frontend/static checks, and opt-in real-model or environment E2E checks.

## CI baseline

The checked-in CI runs:

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests scripts
cd frontend/terminal && npm ci && npx tsc --noEmit
```

Python tests run on 3.10 and 3.11. Ruff and the frontend typecheck run on Python 3.11 and Node 20 respectively. The dashboard has a separate Pages workflow that runs `npm run build` when its source or published assets change.

## Test selection matrix

| Change area | Minimum focused tests | Additional validation |
| --- | --- | --- |
| API/provider/auth | `tests/test_api`, `tests/test_auth`, relevant config tests | Dry-run/profile command checks; real API only with `harness-eval` |
| Agent loop/messages | `tests/test_engine` | Permissions, hooks, tools, compact tests if those paths changed |
| Tool | Matching `tests/test_tools/test_*` | Engine integration-flow test for lifecycle-sensitive tools |
| Permission/sandbox | `tests/test_permissions`, `tests/test_sandbox` | Docker E2E script when Docker behavior changed |
| Settings/CLI/commands | `tests/test_config`, `tests/test_commands`, `tests/test_entrypoints` | `uv run oh --help` and representative dry-run |
| Skills/plugins/hooks/MCP | Corresponding `tests/test_*` directories | `scripts/test_real_skills_plugins.py` only when live evaluation is needed |
| Memory/session/services | `tests/test_memory`, `tests/test_services` | Resume/export manual check for format changes |
| Tasks/swarm/coordinator | `tests/test_tasks`, `tests/test_swarm`, `tests/test_coordinator` | Platform/backend-specific test when applicable |
| Channels/bridge | `tests/test_channels`, `tests/test_bridge` | SDK/live channel tests remain opt-in |
| ohmo | `tests/test_ohmo` | Isolated temporary workspace; gateway manual check if lifecycle changed |
| Python UI/backend | `tests/test_ui` | Terminal E2E scripts for rendering/input changes |
| React terminal | `npx tsc --noEmit` in `frontend/terminal` | `scripts/react_tui_e2e.py` or targeted interaction scripts |
| Autopilot service | `tests/test_autopilot`, `tests/test_services/test_autopilot.py` | Dashboard build and snapshot review |
| Autopilot dashboard | `npm run build` in `autopilot-dashboard` | Inspect generated `docs/autopilot` output |
| Installer/platform | `tests/test_install`, `tests/test_platforms.py` | Test on each affected OS/shell |

## Writing tests

- Mirror the source subsystem under `tests/test_<subsystem>/`.
- Use `tmp_path` and temporary environment variables for settings, sessions, workspaces, and plugin roots.
- Stub provider clients with deterministic streamed events; do not require real credentials in normal tests.
- Assert emitted events or persisted contracts, not private implementation details, when practical.
- Test denial and cleanup paths for security/lifecycle changes.
- For tools, cover schema, successful execution, normalized failure, `is_read_only`, permissions, and sandbox routing as applicable.
- For providers, cover request translation, streamed text/thinking/tool calls, usage, error translation, and multi-turn tool-call replay.
- Avoid timing-only assertions for async/background behavior; wait on an observable condition with a bounded timeout.

## Live and manual evaluation

Real model calls are intentionally separate because they require credentials, cost money, and can be nondeterministic. Use `.claude/skills/harness-eval/SKILL.md` when the user explicitly asks for real API, agent-loop, or end-to-end validation.

For a layered operator-run check of a local Anthropic-compatible model across print mode, the
React terminal, and `ohmo`, follow the
[LM Studio local manual test flow](testing/LM_STUDIO_LOCAL_MANUAL_TEST.md).

Useful existing drivers include:

- `scripts/e2e_smoke.py`
- `scripts/test_harness_features.py`
- `scripts/test_real_skills_plugins.py`
- `scripts/test_docker_sandbox_e2e.py`
- `scripts/react_tui_e2e.py`
- `scripts/test_tui_interactions.py`
- `scripts/test_cli_flags.py`

Read a driver before running it. Some require provider credentials, Docker, an interactive terminal, or external services.

## Validation before handoff

Report exactly what ran and its result. If a relevant check was not run, state why and what remains. Do not use a narrow unit test to claim a cross-subsystem change is fully verified.
