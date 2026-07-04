# Autopilot architecture and ownership

## Inputs and outputs

Autopilot accepts `ohmo_request`, `manual_idea`, `github_issue`, `github_pr`, and
`claude_code_candidate` sources. `RepoAutopilotStore.enqueue_card()` normalizes source reference,
labels, body, timestamps, fingerprint, score, and initial status into `RepoTaskCard`.

Outputs can include registry/journal/context files, worktrees, branches/commits, model and
verification reports, GitHub comments/PRs/check observations, merge operations, and a static
dashboard projection.

## Main components

| Component/function | Ownership |
| --- | --- |
| `RepoTaskCard`, `RepoAutopilotRegistry` | persisted card/registry shape |
| `enqueue_card()` | normalize, fingerprint, deduplicate, merge/update card |
| `_score_card()` / `pick_next_card()` | prioritization and next-card choice |
| `scan_github_issues/prs()` | external candidate intake through `gh` |
| `scan_claude_code_candidates()` | local candidate-file intake |
| `run_next()` / `run_card()` | orchestration and state transitions |
| `_run_agent_prompt()` | shared OpenHarness runtime execution in target cwd |
| `_verification_commands()` | validates policy entries and shell opt-in |
| `_run_verification_steps()` | executes and records command evidence |
| `_upsert_pull_request()` | reuse/create PR for card branch |
| `_wait_for_pr_ci()` | bounded polling and check rollup |
| `_process_existing_pr_card()` | monitor existing PR CI and apply merge/human-gate outcome; no model repair loop |
| `append_journal()` / reports | durable diagnostic evidence |
| `export_dashboard()` | write static snapshot/index projection |

## Storage boundary

`RepoAutopilotStore.__init__()` resolves a repository cwd and `_ensure_layout()` creates:

```text
<repo>/.openharness/autopilot/
  registry.json
  repo_journal.jsonl
  active_repo_context.md
  autopilot_policy.yaml
  verification_policy.yaml
  release_policy.yaml
  runs/
```

The registry has `version: 1`; broader released-format migration is not yet implemented. Registry
and reports use atomic replacement where owned. JSONL journal appends one record and may require
tail-tolerant recovery after abrupt failure.

## Dependency boundaries

Autopilot calls Git/GitHub via bounded subprocess helpers, uses `WorktreeManager`, builds an
OpenHarness runtime for model work, and calls local verification commands. It does not bypass the
shared engine/provider contract, but its default execution policy chooses `full_auto` inside a
worktree. Worktree isolation does not isolate network, GitHub, process, or credential side effects.

## Dashboard boundary

`_build_dashboard_snapshot()` projects cards/journal/focus/counts into JSON. `export_dashboard()`
writes `snapshot.json`, a fallback/static `index.html`, and `.nojekyll`. The Vite application is
separate source that consumes the snapshot for GitHub Pages. Never edit generated asset files to
change service behavior.

## Current constraints

- Store logic is concentrated in one large service module.
- Files and GitHub state are not one transaction.
- Repeated scheduled scans/ticks rely on fingerprints/source refs and status checks for idempotency.
- `gh` output, issue bodies, PR bodies, check summaries, and labels are external inputs.
- The process has no distributed lease preventing two hosts from operating the same repository.
- Declared decision/release human-gate fields are not enforced by the current merge decision.
- Reserved statuses outnumber the transitions currently emitted by the service.
