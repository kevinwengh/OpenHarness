---
name: openharness-development
description: Analyze, implement, refactor, debug, document, or review changes in the OpenHarness repository while preserving its runtime, safety, persistence, extension, UI, and ohmo boundaries. Use for general OpenHarness development tasks that are not specifically adding a model provider or tool, including CLI, engine, memory, plugins, MCP, hooks, sandbox, tasks, swarm, channels, autopilot, frontend, and ohmo changes.
---

# OpenHarness development

Use repository evidence to make a focused change and verify every affected boundary.

## Establish scope

1. Read the root `AGENTS.md`.
2. Read `docs/ARCHITECTURE.md` and the relevant section of `docs/DEVELOPMENT.md`.
3. Inspect the owning source and nearest tests; do not rely on README feature claims alone.
4. Read [references/change-map.md](references/change-map.md) to identify cross-subsystem seams.
5. Classify the task as core runtime, extension, UI, automation, or ohmo-specific.

For tool work, invoke `openharness-add-tool`. For provider/auth/client work, invoke `openharness-add-provider`.

## Implement

1. Reproduce or encode the intended behavior in a focused test.
2. Change the narrowest owning module.
3. Preserve async behavior, typed boundaries, normalized errors, and cleanup.
4. Trace any composition change through `src/openharness/ui/runtime.py`.
5. Trace any agent-loop change through permissions, hooks, sandbox routing, stream events, message persistence, and continuation.
6. Keep reusable behavior in `src/openharness`; keep personal workspace/gateway behavior in `ohmo`.
7. Update documentation and `CHANGELOG.md` when user-visible behavior or a documented contract changes.

## Verify

1. Read `docs/TESTING.md` and run the narrowest relevant tests first.
2. Run Ruff on touched Python paths, then the CI command before handoff when practical.
3. Run TypeScript/build checks for either affected frontend.
4. Keep normal tests offline and deterministic.
5. Use `harness-eval` only for explicitly requested or justified real-model validation.
6. Report commands and results precisely; state any unrun relevant checks.

## Commit and hand off

When the user authorizes a commit:

1. Follow the root `AGENTS.md` **Create reviewable commits** policy; it is the canonical commit
   contract for both Codex and Claude.
2. Reinspect status plus staged and unstaged diffs after validation so unrelated user work is not
   included accidentally.
3. Create a specific Conventional Commit subject and a substantive body explaining motivation,
   behavioral or boundary impact, and relevant trade-offs.
4. End the body with an honest `Validation:` section listing only checks actually completed, or
   explicitly state why validation was not run.
5. Report the commit hash, subject, validation outcome, and any intentionally uncommitted files in
   the handoff.

## Guardrails

- Preserve sensitive-path denial and project-plugin opt-in trust.
- Do not expose credentials in logs, diagnostics, fixtures, or docs.
- Do not couple core modules to `ohmo`.
- Do not mutate generated dashboard assets manually when source changes can regenerate them.
- Do not claim cross-subsystem verification from a single narrow test.
