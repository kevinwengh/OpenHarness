# OpenHarness contributor instructions

These instructions apply to the whole repository.

## Start with current-state evidence

- Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the subsystem's source and tests before changing behavior.
- Treat `src/openharness/ui/runtime.py` as the composition root and `src/openharness/engine/query.py` as the tool-loop execution path.
- Preserve the separation between the reusable `openharness` runtime and the `ohmo` application built on it.
- Do not infer compatibility from a provider name alone. Trace settings, auth resolution, client selection, request conversion, and tests.

## Make focused changes

- Add behavior at the narrowest owning boundary; avoid growing `cli.py`, `commands/registry.py`, or `ui/runtime.py` when a subsystem module can own it.
- Keep tools asynchronous and return `ToolResult`; define inputs with Pydantic and declare read-only behavior accurately.
- Keep permissions, hooks, sandbox routing, session persistence, and stream events intact when changing the agent loop.
- Project skills belong in `.claude/skills/<name>/SKILL.md`; runtime-bundled skills belong in `src/openharness/skills/bundled/content/`.
- Project plugins are untrusted and disabled unless `allow_project_plugins` is enabled. Do not weaken that default.
- Never add credentials, generated session data, or personal `~/.openharness` / `~/.ohmo` state to the repository.

## Verify proportionally

Use [docs/TESTING.md](docs/TESTING.md) to select tests. The normal pre-PR baseline is:

```bash
uv run ruff check src tests scripts
uv run pytest -q
cd frontend/terminal && npm ci && npx tsc --noEmit
```

Run the frontend command only when frontend code, its protocol, packaging, or launcher changes. Run `autopilot-dashboard`'s build when that dashboard changes. Real model calls are opt-in and use `.claude/skills/harness-eval`; unit tests must not require credentials or network access.

## Keep documentation synchronized

- Update [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) when boundaries, flows, or state ownership change.
- Update [docs/EXTENDING.md](docs/EXTENDING.md) when extension contracts change.
- Update [docs/TESTING.md](docs/TESTING.md) when validation commands or CI gates change.
- Add a concise `CHANGELOG.md` entry under `Unreleased` for user-visible behavior.
- Keep examples executable and file references real.

## Repository-specific skills

- Use `openharness-development` for general implementation and maintenance.
- Use `openharness-add-tool` for built-in or plugin tool work.
- Use `openharness-add-provider` for provider, auth, API client, or model-compatibility work.
- Use `harness-eval` only when real API/end-to-end model validation is requested or justified.
- Use `pr-merge` for external pull-request integration.
