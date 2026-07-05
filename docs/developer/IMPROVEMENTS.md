# Codebase improvement backlog

This is an evidence-backed technical assessment, not a release commitment. It was prepared against
commit `95fd039` plus the documentation working tree on 2026-07-04. Revalidate the evidence before
implementing an item because active development may have changed the tradeoffs.

## How priorities are assigned

- **P1 — structural risk:** a boundary or feedback-loop weakness that makes many changes harder or
  undermines an explicit repository invariant.
- **P2 — quality leverage:** work that improves defect detection, maintainability, or compatibility
  across a meaningful subsystem.
- **P3 — scale/readiness:** valuable hardening that should follow measurement or a clearer product
  requirement.

The recommended order is to establish guardrails before broad refactors: make typing/coverage and
frontend behavior measurable, then split hotspots behind tests, and keep product-boundary work in
small compatibility-preserving steps.

## Evidence snapshot

| Signal | Observed on this snapshot |
| --- | --- |
| Python implementation | 229 files under `src/openharness`, 19 under `ohmo`; about 76,451 lines in total |
| Python tests | 103 `test_*.py` files; 1,159 tests collected by pytest |
| CI test matrix | Full pytest suite on Python 3.10 and 3.11 |
| Other CI gates | Ruff, documentation integrity, and a TypeScript typecheck for `frontend/terminal` |
| Largest implementation files | 3,981-line command registry, 3,253-line autopilot service, 3,229-line CLI |
| Configured but non-gating tooling | Strict mypy and pytest-cov are installed; neither currently runs in CI |

Line counts are navigation signals, not quality scores. They matter here because the largest files
also combine registration/composition with multiple domain responsibilities.

## Priority summary

| Priority | Improvement | Why it matters |
| --- | --- | --- |
| P1 | Enforce or remove declared autopilot policy gates | Prevents operators relying on non-enforced merge/retry controls |
| P1 | Remove reverse `openharness` → `ohmo` dependencies | Restores the declared reusable-runtime/application boundary |
| P1 | Complete the ohmo memory-backend boundary | Prevents personal sessions from reading/writing unexpected core memory paths |
| P1 | Decompose responsibility hotspots | Reduces regression radius and makes ownership discoverable |
| P1 | Establish an incremental static-typing gate | Turns an existing strict configuration into usable feedback |
| P2 | Add automated frontend behavior tests | Typechecks do not verify terminal interactions or rendering |
| P2 | Publish coverage and define risk-based targets | 1,159 collected tests provide no visible coverage map or floor |
| P2 | Version persisted and extension contracts | Makes compatibility and migrations explicit instead of implicit |
| P2 | Expand documentation integrity | Existing structural checks do not validate anchors, Mermaid syntax, or command semantics |
| P3 | Measure concurrency and long-running runtime limits | Defines safe operating envelopes before scale-driven rewrites |
| P3 | Add a checked-in release workflow | Reduces manual version/package/publication drift |

## P1: enforce or remove declared autopilot policy gates

**Evidence.** `release_policy.yaml` declares `merge_requires_human`, `release_requires_human`, and
`auto_revert_on_failed_verification`, while `_automerge_eligible()` reads only the GitHub auto-merge
mode/label and PR draft state. Likewise, `decision.default_human_gate`, `repair.retry_on`, and
`repair.stop_on` are loaded and exposed to prompts, but do not drive service transitions. Malformed
policy YAML silently falls back to defaults. The persisted status vocabulary also contains
`accepted`, `pr_open`, `rejected`, and `superseded`, which current service paths do not emit.

**Risk.** Operators can reasonably interpret declared fields as enforced controls and enable
scheduled/full-auto work under a false safety assumption. Documentation can reduce that risk but
cannot substitute for fail-closed policy enforcement.

**Recommended direction.** Define one validated policy model and make each field either enforced or
explicitly advisory. Fail closed on invalid safety policy, apply release human gates in the merge
decision, use retry/stop classifications consistently, and either implement reserved status
transitions or deprecate them with migration handling.

**Done when.** Tests prove each gate at the final side-effect boundary, invalid policy prevents
operation with an actionable diagnostic, the generated/default files contain no inert safety
fields, and the state diagram matches transitions emitted by service tests.

## P1: remove reverse dependencies from core into ohmo

**Evidence.** The intended layering is `ohmo` → `openharness`, but core currently imports `ohmo` in:

- `channels/impl/base.py` for an `OHMO_WORKSPACE` attachment directory;
- `channels/impl/feishu.py` for managed-group lookup;
- `services/cron_scheduler.py` for gateway configuration and Feishu notification;
- a bundled skill example that imports the `ohmo` workspace helper.

**Risk.** The reusable package knows application-specific workspace and gateway details. This makes
core reuse, optional installation, isolated tests, and future application composition harder.

**Recommended direction.** Introduce small core-owned protocols/callbacks for media-root resolution,
group policy lookup, and notification delivery. Register `ohmo` adapters at composition time. Keep
fallback core behavior explicit and cover the no-`ohmo` installation path.

**Done when.** `rg -n 'from ohmo|import ohmo' src/openharness --glob '*.py'` returns no runtime
imports; core tests pass without importing `ohmo`; `ohmo` integration tests prove equivalent media,
group-policy, and notification behavior.

## P1: complete the ohmo memory-backend boundary

**Evidence.** ohmo injects a personal `MemoryCommandBackend` and disables normal project-memory
prompt reads, but the adapter is not used throughout the lifecycle:

- `QueryEngine._extract_durable_memories()` calls the project-memory extractor using the effective
  cwd even when an ohmo backend is active;
- shared `/memory validate`, `session`, `team`, and `agent` handlers call core path helpers;
- automatic session-memory files are stored under the core cwd-hashed data directory;
- personal recall selects the first five filenames without query relevance or usage accounting;
- cached runtimes retain the personal-memory prompt captured at construction; and
- auto-dream's core runner uses broad full-auto permissions with prompt-only path constraints,
  while the ohmo runner does not force a permission mode and may be unable to apply changes under
  default non-interactive permissions.

**Risk.** “Project memory disabled” can be interpreted as a complete isolation guarantee when it is
currently only the normal prompt-read behavior. Opting into automatic extraction can persist
personal-channel content in project memory. Diagnostics may inspect the wrong store, session
continuity is split across roots, personal-memory changes can remain stale in cached channels, and
dream safety/effectiveness differs by runner.

**Recommended direction.** Replace the command-only adapter with one core-owned memory context that
defines durable store, prompt recall, extraction writes, validation/migration, usage accounting,
session-memory location, consolidation directories, and runner permission/tool policy. Pass that
context into `QueryEngine` and commands. Make runtime refresh invalidate/rebuild personal prompt
content, add relevance/usage behavior appropriate to personal memory, and enforce dream filesystem
scope at a tool/permission boundary rather than only in the model prompt.

**Done when.** Tests prove every ohmo memory read/write stays in explicitly documented roots,
automatic extraction writes personal memory or is disabled by construction, every `/memory`
subcommand reports the same active store semantics, cached bundles observe a defined refresh model,
personal recall/staleness is deterministic, and both project/personal dream runners can edit only
the selected memory directory under equivalent tested permissions.

## P1: decompose responsibility hotspots

**Evidence.** Current line counts include `commands/registry.py` (2,783), `cli.py` (2,551),
`autopilot/service.py` (2,239), `services/compact/__init__.py` (1,725), `config/settings.py` (1,104),
`engine/query.py` (1,057), and `ui/runtime.py` (799). The first two mix registration with substantial
domain behavior; the query and runtime files sit on nearly every request path.

**Risk.** Large multi-responsibility modules obscure ownership, increase merge conflicts, and make a
local edit appear safe when it crosses persistence, security, or UI contracts.

**Recommended direction.** Extract cohesive modules behind existing entrypoints: command families,
setup/dry-run CLI services, query metadata/artifact helpers, compaction strategies, and runtime
builders. Preserve public imports and registration order initially. Use characterization tests before
moving behavior; do not combine extraction with functional redesign.

**Done when.** Each extracted area has one named owner, focused tests no longer require a monolithic
registry/runtime fixture, compatibility imports are documented, and the original composition files
primarily wire components rather than implement domain policy.

## P1: establish an incremental static-typing gate

**Evidence.** `pyproject.toml` declares strict mypy settings and installs mypy, but CI only runs Ruff
and pytest. On this snapshot, `uv run mypy --explicit-package-bases src/openharness` reports 1,187
errors across 189 files, including package-resolution noise and actionable generic/return/optional
errors. `CONTRIBUTING.md` therefore describes mypy as optional.

**Risk.** Type hints communicate intent but regressions are not gated; a repository-wide strict
switch is currently too noisy to adopt safely.

**Recommended direction.** First make module resolution deterministic for the `src` layout. Add a
small strict allowlist for stable contracts such as tool base types, message/event models, and new
modules. Ratchet the allowlist or error baseline down; never hide new errors with a global
`ignore_errors` setting.

**Done when.** A documented mypy command is deterministic locally and in CI, changed/new code in
the selected modules cannot add errors, and an owner-visible trend tracks the remaining baseline.

## P2: add automated frontend behavior tests

**Evidence.** `frontend/terminal/package.json` has only a `start` script; the dashboard has `dev`,
`build`, and `preview`. CI typechecks the terminal and the Pages workflow builds the dashboard, but
neither package defines a JavaScript test command. Python UI tests and manual E2E drivers cover some
protocol behavior, but they do not directly exercise React component state and rendering.

**Risk.** Keyboard handling, permission dialogs, streaming row grouping, Markdown rendering, and
dashboard state presentation can regress while both TypeScript and Python tests remain green.

**Recommended direction.** Add a lightweight component test stack and start with protocol/event
reducers and previously fixed interaction regressions. Keep terminal escape-sequence E2E tests
separate from fast component tests. Add dashboard fixtures for empty, partial, failed, and large
snapshots.

**Done when.** Both frontend packages expose deterministic test commands, CI runs them, and critical
rendering/input states have regression cases independent of live models and real terminals.

## P2: publish coverage and define risk-based targets

**Evidence.** Pytest collects 1,159 tests and `pytest-cov` is installed, but CI runs `pytest -q`
without a coverage report, configuration, artifact, or threshold. Test volume alone cannot identify
untested denial, cleanup, platform, or error branches.

**Risk.** Contributors cannot see whether a seemingly well-tested subsystem has critical blind
spots, and a global percentage introduced later could reward low-value lines instead of important
contracts.

**Recommended direction.** Publish branch coverage first without a blocking threshold. Categorize
gaps in high-risk modules (engine, permissions, auth, persistence, process cleanup). Add per-area
floors or changed-line expectations only after measuring a stable baseline; retain explicit tests
for invariants rather than using percentage as their proxy.

**Done when.** CI provides an inspectable branch-coverage artifact/trend, exclusions are justified,
and the contribution guide explains which security/lifecycle contracts require direct tests.

## P2: version persisted and extension contracts

**Evidence.** Memory files have a schema version and migration path, and settings contain at least
one compatibility migration. Architecture documentation currently identifies formal compatibility
for settings, plugin Python APIs, and persisted session metadata as unknown. Session/tool metadata,
plugin contracts, and several file-backed services do not share a documented versioning policy.

**Risk.** Stored state and third-party extensions can break across releases without a clear
compatibility window, migration hook, or diagnostic path.

**Recommended direction.** Inventory persisted formats and extension APIs, label each public or
internal, add explicit schema versions where evolution is expected, and define load-time migration
and unsupported-version errors. Start with sessions/tool metadata because they are required for
continuation, then plugins/settings. Add fixtures from released formats.

**Done when.** Every durable format has an owner and compatibility policy, migrations are idempotent
and tested against old fixtures, and extension authors can tell which contracts follow semantic
versioning.

## P2: expand documentation integrity

**Evidence.** Maintained Markdown now spans setup, architecture, development, extension, testing,
onboarding, and improvement references. `scripts/check_docs.py` now checks local targets,
unambiguous repository paths, fenced-block balance, SVG XML/titles, and source-derived registry
counts in CI. It does not parse heading anchors, lint Markdown style, compile Mermaid diagrams, or
execute safe command examples.

**Risk.** File moves, renamed headings, CLI option changes, and stale commands can break the shortest
onboarding path without affecting code tests.

**Recommended direction.** Extend the dependency-free foundation with heading-anchor checks and a
Markdown linter. Compile Mermaid through a pinned tool, validate safe commands such as `oh --help`,
and collect shell snippets needing manual/external prerequisites into an explicit allowlist. Do not
execute credentialed/live examples in normal CI.

**Done when.** CI rejects broken local links and malformed docs, setup/validation commands have an
owner, and generated `docs/autopilot/` output is excluded from hand-maintained checks where needed.

## P3: measure concurrency and long-running runtime limits

**Evidence.** The system uses an in-memory channel bus, filesystem mailboxes, background
subprocesses, and a per-conversation `ohmo` runtime pool. Architecture documentation records their
production scale limits as unknown. Tests exercise behavior but no checked-in benchmark/load suite
defines throughput, queue bounds, pool eviction, mailbox contention, or long-session memory limits.

**Risk.** Resource leaks, unbounded growth, and contention may only appear in gateways or long-lived
multi-agent sessions; premature rewrites would be equally unsupported without measurement.

**Recommended direction.** Add observable counters and repeatable stress fixtures for concurrent
messages, runtime creation/cleanup, mailbox writers, task cancellation, and long histories. Define
service-level targets from actual deployment needs, then introduce backpressure, eviction, or storage
changes where evidence shows a limit.

**Done when.** Operators can observe queue/pool/task size and lifecycle failures, a repeatable suite
documents the tested envelope, and limits/failure behavior are explicit in configuration or docs.

## P3: add a checked-in release workflow

**Evidence.** The package version is maintained in `pyproject.toml`, CLI/version strings and release
notes must remain synchronized, and `docs/DEVELOPMENT.md` states that build/publication steps are not
defined in a checked-in release workflow.

**Risk.** Manual release steps can publish inconsistent metadata, omit packaged frontend assets, or
skip validation and artifact inspection.

**Recommended direction.** Document and then automate a dry-run build, wheel/sdist inspection,
entrypoint smoke tests, packaged frontend verification, changelog/version checks, and trusted
publication with an explicit approval gate.

**Done when.** A maintainer can reproduce release artifacts from a tag, CI verifies their contents
and entrypoints, publication permissions are least-privilege, and rollback/yank steps are documented.

## Reassessment checklist

Before accepting an improvement item into a milestone:

- [ ] Re-run or inspect the cited evidence on the target branch.
- [ ] Define the observable behavior that must not change.
- [ ] Split functional changes from mechanical extraction where possible.
- [ ] Identify security, persistence, provider, UI, and `ohmo` boundary effects.
- [ ] Select focused and broader checks from `docs/TESTING.md`.
- [ ] Update this backlog when the evidence, priority, or completion state changes.
