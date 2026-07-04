# Autopilot operations

Use autopilot only in a repository where automated worktree creation, model-driven edits,
verification commands, branch pushes, PR comments, and optional merge are acceptable.

## Preflight

1. Read all three files under `.openharness/autopilot/`:
   `autopilot_policy.yaml`, `verification_policy.yaml`, and `release_policy.yaml`.
2. Confirm base branch, branch prefix, attempt/repair limits, and model/turn settings.
3. Set `autopilot.github.auto_merge.mode: pr_only` initially. The similarly named
   `merge_requires_human` and `release_requires_human` release-policy fields are not enforced by
   the current merge decision.
4. Review every verification command. Shell syntax is rejected unless the mapping explicitly sets
   `shell: true`.
5. Confirm `git`/`gh` identity, remote, permissions, and clean primary checkout.
6. Run status/list/context before `run-next`.

## Operate

```bash
oh autopilot status --cwd /repo
oh autopilot list --cwd /repo
oh autopilot context --cwd /repo
oh autopilot run-next --cwd /repo
```

`RepoAutopilotStore.run_next()` picks the highest-scored queued card and delegates to `run_card()`.
Observe registry status, JSONL journal, active context, worktree/branch, run report, verification
report, PR, and CI together; no single file proves completion.

## State transitions

The current main path is `queued` → `preparing` → `running` → `verifying`, then `completed` or
`waiting_ci`. Repair loops move failed verification/CI into `repairing`, then back through
verification. A green human-gated PR is recorded as `completed` with linked PR metadata; it is not
the same as `merged`.
Terminal failure/rejection/supersession should include journal and report evidence.

See [Autopilot state machine](../developer/autopilot/STATE_MACHINE.md) for detailed transition
ownership.

## Human and merge gates

Automatic merge additionally requires the configured label (default `autopilot:merge`) and passing
CI when the mode is `label_gated`. In `fully_auto` mode the label is not required; draft PRs remain
ineligible. A label is authorization, not correctness evidence. Review the PR diff, verification
commands/output, base synchronization, and unresolved comments before applying it.

`release_policy.yaml` is prompt context today, not an enforced merge guard. The effective merge
decision is `RepoAutopilotStore._automerge_eligible()`.

## Recovery

| Failure | Recovery approach |
| --- | --- |
| Agent runtime error | preserve report/journal; validate profile and retry policy before requeue |
| Local verification failure | inspect exact argv/shell opt-in and repair report |
| CI timeout/failure | inspect check rollup and GitHub state; avoid blind repeated comments |
| Merge conflict | stop automated repair, sync/rebase with human review |
| Orphan worktree | correlate card/branch/reports, preserve changes, then use worktree cleanup tools |
| Corrupt registry | stop cron/ticks, back up entire autopilot directory, validate JSON/version |

Autopilot does not provide transactional rollback for pushed commits, comments, PRs, or merges.
Recovery must consider external GitHub state as well as local files.

## Scheduled operation

`install_default_cron()` creates scan and tick jobs in the shared local cron registry. The scheduler
must run on an awake host with the repository, credentials, CLI tools, and environment available.
Use only one logical scheduler owner and make intake/execution idempotent.
