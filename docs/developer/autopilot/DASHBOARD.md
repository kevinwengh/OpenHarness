# Autopilot dashboard: data contract, rendering, and publication

The autopilot dashboard is a read-only static projection of repository-autopilot state. It turns
the file-backed card registry, selected metadata, and recent journal entries into a browser Kanban
view. It is not the autopilot engine and is not a control plane: it cannot enqueue work, run an
agent, alter policy, approve a permission, reconcile GitHub, or merge a pull request.

This document distinguishes:

- **Observed behavior** directly implemented by the current source and workflows;
- **inferred build risk** caused by the interaction of the exporter and Vite public assets; and
- **generated output** under `docs/autopilot/`, which is not hand-maintained source.

## System boundary

![Autopilot intake, execution, gates, and projections](../../architecture/diagrams/autopilot-architecture.svg)

```text
issues / PRs / manual ideas / ohmo requests / local candidates
                              |
                              v
              .openharness/autopilot/ registry + journal
                              |
                  RepoAutopilotStore state changes
                              |
                              v
                  _build_dashboard_snapshot()
                              |
                              v
                   docs/autopilot/snapshot.json
                              |
                              v
                    React/Vite static dashboard
                              |
                              v
                         GitHub Pages
```

| Boundary | Owner | Responsibility |
| --- | --- | --- |
| Task state and orchestration | [`RepoAutopilotStore`](../../../src/openharness/autopilot/service.py) | intake, scoring, execution, status, verification, PR/CI, repair, merge, journal |
| Snapshot export | [`export_dashboard()`](../../../src/openharness/autopilot/service.py) | serialize current store state and write static output |
| Snapshot types and status groups | [`types.ts`](../../../autopilot-dashboard/src/types.ts) | TypeScript display contract and Kanban grouping |
| Browser rendering | [`App.tsx`](../../../autopilot-dashboard/src/App.tsx) | fetch snapshot once, filter cards, render counters/board/journal |
| Frontend build | [`vite.config.ts`](../../../autopilot-dashboard/vite.config.ts) | build the React app into `docs/autopilot/` |
| Scheduled refresh | [`autopilot-scan.yml`](../../../.github/workflows/autopilot-scan.yml), [`autopilot-run-next.yml`](../../../.github/workflows/autopilot-run-next.yml) | scan or run work, export, commit generated output |
| Publication | [`autopilot-pages.yml`](../../../.github/workflows/autopilot-pages.yml) | build and deploy `docs/autopilot/` to GitHub Pages |

The authoritative state is not the dashboard. Diagnose a run by reconciling the registry, journal,
active context, run/verification reports, Git branch/worktree, PR/check/merge state, and scheduler
history. The dashboard can be stale even when all those sources are valid.

## Generation lifecycle

### Automatic generation after state changes

`RepoAutopilotStore.rebuild_active_context()` writes `active_repo_context.md` and then calls
`export_dashboard()`. Important paths such as card enqueue/update and completed source scans rebuild
the active context, so dashboard generation is often a side effect of normal autopilot mutation.

A bare `append_journal()` call does not itself export. Freshness depends on whether its caller later
rebuilds active context or explicitly exports.

### Explicit export

The CLI exposes the same operation:

```bash
uv run oh autopilot export-dashboard --cwd /path/to/repository
```

Use `--output /path/to/output` to choose a different target. Without it, the exporter writes:

```text
<repo>/docs/autopilot/
  snapshot.json
  index.html
  .nojekyll
```

Writes use `atomic_write_text()`, so each individual file is replaced atomically. The three files
are not one transaction: a process failure can leave output from different generations.

`export_dashboard()` always writes a minimal fallback `index.html`, even if a React build already
exists in the directory. Running export after `npm run build` therefore replaces the React entry
page until the dashboard is built again. Existing hashed assets may remain because neither export
nor the Vite build empties the output directory.

## Snapshot contract

`RepoAutopilotStore._build_dashboard_snapshot()` produces this top-level shape:

| Field | Meaning | Displayed by React? |
| --- | --- | --- |
| `generated_at` | exporter wall-clock time in Unix seconds | yes |
| `repo_name` | repository directory name | indirectly in data, not current heading |
| `repo_path` | absolute repository path | no, but publicly readable in JSON |
| `focus` | first card in the current status-priority selection | yes |
| `counts` | card count by persisted status | yes |
| `status_order` | exporter status vocabulary/order | not directly |
| `columns` | serialized cards grouped by exact status | yes |
| `cards` | all serialized cards in exporter sort order | no; frontend reads `columns` |
| `journal` | latest 30 journal entries in stored order | yes, reversed to newest-first |
| `policies` | absolute paths to the three policy files | no, but publicly readable in JSON |
| `active_context` | complete generated active repository context | no, but publicly readable in JSON |

Cards contain their full title/body, status, source kind/reference, score/reasons, labels, creation
and update times, plus selected metadata. `_serialize_card()` exposes:

- last note and source URL;
- execution model and assistant-summary preview;
- attempt and maximum-attempt counts;
- human-gate and verification-failure flags;
- linked PR number and URL;
- CI conclusion/summary;
- failure stage/summary; and
- verification command, status, and return code.

The serializer omits full verification stdout/stderr and most arbitrary card metadata. That is data
minimization, not content redaction: titles, bodies, notes, references, summaries, commands, journal
metadata, and active context can still contain private or hostile text.

## Focus, sorting, and status vocabulary

Cards are sorted by status priority, then descending score, descending update time, and title. The
snapshot chooses focus from the first non-empty status bucket in this order:

```text
repairing -> waiting_ci -> running -> verifying -> preparing -> accepted -> queued
```

The persisted status vocabulary and dashboard contain:

```text
queued, accepted, preparing, running, verifying, pr_open, waiting_ci,
repairing, completed, merged, failed, rejected, superseded
```

The current normal service path does not write `accepted`, `pr_open`, `rejected`, or `superseded`.
Those are reserved schema/dashboard states, not evidence of implemented lifecycle transitions. See
[the state-machine reference](STATE_MACHINE.md) for emitted paths.

## React dashboard behavior

On mount, `App` performs one request:

```text
GET ./snapshot.json     cache: no-store
```

There is no polling, WebSocket, service worker, or refresh button. `no-store` avoids using a normal
cached response, but the page must be reloaded after a newer snapshot is deployed.

### Visible sections

1. **Hero and current focus** — status, title, score, and source kind for the selected focus card.
2. **Summary counters** — To Do, In Progress, In Review, and Done.
3. **Filter** — case-insensitive substring search across ID, title, full body, source kind/reference,
   labels, and score reasons.
4. **Kanban board** — four presentation groups:

   | Group | Statuses |
   | --- | --- |
   | To Do | `queued`, `accepted` |
   | In Progress | `preparing`, `running`, `repairing` |
   | In Review | `verifying`, `pr_open`, `waiting_ci` |
   | Done | `completed`, `merged`, `failed`, `rejected`, `superseded` |

5. **Cards** — ID, status, title, first 260 body characters, labels/source, score, relative update
   time, source reference, last note, and one selected verification/CI/failure/gate summary.
6. **Recent journal** — the exported journal entries in reverse order.

`HeroBackground` and `PipelineAnimation` are decorative SMIL/SVG animations. Their QUEUE, PREP,
RUN, CHECK, and MERGE display is not connected to live event telemetry.

### Counter semantics and current inconsistencies

The top counters are presentation summaries, not a partition of cards:

- To Do renders only `queued`, although its caption says “queued + accepted.”
- In Progress also counts `accepted`, `verifying`, `pr_open`, and `waiting_ci`, while In Review
  counts the latter three again.
- Done combines successful and failed outcomes.
- `superseded` appears in the Done column but is omitted from the Done counter.

Use `counts` or `columns` from the raw snapshot when exact status cardinality matters.

## Scheduled refresh and Pages deployment

### Intake scan

The scan workflow runs every 30 minutes on a self-hosted runner:

1. checkout with `clean: false`;
2. install Python dependencies;
3. run `oh autopilot scan all`;
4. explicitly export the dashboard; and
5. commit/push `docs/autopilot` when it changed.

### Run-next tick

The run-next workflow runs every two hours on a self-hosted runner. It invokes `autopilot tick`,
which scans and may execute the highest-priority queued card, then exports and commits the dashboard.

The scan and run-next workflows use different concurrency groups. They can overlap and operate on
the same local repository/remote branch. File atomicity does not provide a cross-workflow or
distributed lease, so concurrent registry changes and Git pushes remain an operational risk.

### Pages

On relevant pushes to `main`, the Pages workflow:

1. installs Node 20 dependencies under `autopilot-dashboard/`;
2. runs `npm run build`;
3. uploads `docs/autopilot/`; and
4. deploys the artifact to GitHub Pages.

The Pages concurrency group cancels an older in-progress Pages deployment. It does not coordinate
with scan or execution workflows.

## Frontend build and snapshot-source hazard

The Vite app contains [`autopilot-dashboard/public/snapshot.json`](../../../autopilot-dashboard/public/snapshot.json),
while the Python exporter writes `docs/autopilot/snapshot.json`. At the time of this review, the two
checked-in files are byte-identical empty snapshots from 2026-04-16 and include an absolute former
developer path.

**Inferred build risk:** Vite normally copies `public/` files into its output directory. The build
output is `docs/autopilot/`, so `public/snapshot.json` can replace the freshly exported snapshot
during `npm run build`. The workflows export first and build later. There is no focused test proving
that a non-empty Python snapshot survives the build.

Until this is fixed and tested, inspect the deployed/raw `snapshot.json` rather than assuming a
successful Pages deployment contains the latest registry state. A robust design should have one
snapshot source, for example by removing the placeholder from `public/` or by making the workflow
copy the freshly exported snapshot into an isolated build directory after Vite processes assets.

## Privacy and publication boundary

The React UI truncates card bodies, but the downloadable JSON contains full serialized values and
additional fields that the UI does not render. Before publishing, review at least:

- full issue/PR/manual candidate bodies and source references;
- absolute repository and policy paths;
- active repository context;
- labels, notes, score reasons, CI/failure summaries, and verification commands;
- linked PR URLs and journal metadata; and
- repository visibility and Pages access policy.

Do not put credentials, private prompts, customer data, secret URLs, or sensitive command output in
autopilot card text or metadata. The exporter performs shape selection, not secret detection or DLP.
See [Data handling](../../security/DATA_HANDLING.md) for the broader retention boundary.

## Local inspection and development

Inspect current generated JSON without starting a server:

```bash
python -m json.tool docs/autopilot/snapshot.json
```

Export current repository state and serve the fallback/current output:

```bash
uv run oh autopilot export-dashboard --cwd .
python -m http.server 8000 --directory docs/autopilot
```

Build the React source:

```bash
cd autopilot-dashboard
npm ci
npm run build
npm run preview
```

Because of the two-snapshot hazard, compare the generated timestamp and card count before and after
the build. Do not commit a build merely to test documentation. Do not edit hashed files under
`docs/autopilot/assets/`; change `autopilot-dashboard/src/` and rebuild.

## Verification coverage and gaps

[`test_autopilot_export_dashboard_writes_static_site()`](../../../tests/test_services/test_autopilot.py)
verifies that the Python exporter writes fallback HTML and JSON containing cards/status order. The
Pages workflow verifies that TypeScript and Vite can build during deployment.

There is currently no automated test for:

- exporter JSON against the TypeScript `Snapshot` contract;
- survival of fresh snapshot data through `npm run build`;
- counter and Kanban-group consistency;
- malformed/partial snapshot diagnostics;
- automatic refresh behavior;
- privacy/redaction policy; or
- scan/run-next concurrency and push conflicts.

## Safe change checklist

When changing the dashboard or exporter:

1. preserve the registry as authoritative state and the dashboard as a projection;
2. update Python serialization and TypeScript types together;
3. test empty, active, failed, human-gated, and large snapshots;
4. test a non-empty exported snapshot through the actual Vite build;
5. verify every counter against its displayed status groups;
6. keep untrusted text rendered through React escaping; do not introduce raw HTML;
7. review exported fields for privacy and path disclosure;
8. run `uv run pytest -q tests/test_services/test_autopilot.py`;
9. run `npm ci && npm run build` under `autopilot-dashboard/`; and
10. inspect the final `docs/autopilot/snapshot.json`, entrypoint, and assets before publication.
