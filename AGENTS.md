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

## Create reviewable commits

When the user authorizes a commit, Codex, Claude, and other coding agents must apply all of these
rules:

- Inspect `git status`, the unstaged diff, and the staged diff before committing. Stage only the
  intended logical change and leave unrelated or user-owned files untouched.
- Use a Conventional Commit subject for project-authored commits:
  `<type>(<optional-scope>): <imperative summary>`. Keep it specific, under 72 characters, and do
  not end it with a period.
- Every agent-created commit must have a substantive body; subject-only commits are not acceptable.
  Explain why the change is needed, what behavior or contract changes, and any important design,
  safety, compatibility, generated-asset, or trade-off considerations. Do not merely repeat the
  file list or subject.
- End the body with a `Validation:` section that names only checks actually run and their outcome.
  If no checks were appropriate or possible, write `Validation: Not run (<reason>)` rather than
  implying unverified success.
- Keep one logical change per commit. Split unrelated feature, refactor, test, and documentation
  work unless they are inseparable parts of the same behavior change.
- Avoid vague messages such as `update`, `changes`, `fix stuff`, or `WIP`. Preserve original author
  attribution when integrating external work, and explain conflict-resolution decisions in any
  agent-created merge commit. A fast-forward merge creates no new commit and needs no message.
- Never fabricate validation, bypass hooks with `--no-verify`, or amend a published commit unless
  the user explicitly authorizes it.

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
