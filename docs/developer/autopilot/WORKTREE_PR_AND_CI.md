# Worktree, PR, and CI lifecycle

## Preparation

`run_card()` derives a head branch from configured prefix/card identity and uses
`WorktreeManager` when enabled. `_sync_worktree_to_base()` aligns the working branch with the base
and can recognize/reuse prior branch progress on retry.

The primary checkout may already contain user changes. Autopilot must not reset or clean unrelated
work. Worktree creation/removal and branch reuse require explicit ownership evidence.

## Agent execution

`_build_execution_prompt()` combines the task card and policy context.
`_run_agent_prompt()` builds a runtime in the target cwd, streams assistant/error events, and closes
the runtime. Model output is not completion evidence; Git diff and verification decide progress.

## Commit and push

After successful local work, `_git_has_changes()` and `_git_commit_all()` create progress when
needed. `_git_push_branch()` publishes the head. Commands use helper boundaries `_run_git()` and
`_run_gh()` so failures can be classified and reported.

Do not broaden these helpers to shell-evaluate untrusted branch, issue, or card text.

## Pull request lifecycle

`_find_open_pr_for_branch()` and `_upsert_pull_request()` reuse an existing PR where possible.
PR body/comment helpers communicate started, opened, failed, human-gate, and merged states.
Idempotency matters because retries and scheduler restarts can revisit the same card.

## CI evaluation

`_pr_status_snapshot()` loads remote PR/check state. `_ci_rollup()` classifies checks and
`_wait_for_pr_ci()` polls with configured interval, timeout, no-check grace, and settle windows.

“No checks yet” is pending during the grace period. A successful snapshot should remain settled
long enough to reduce races with checks that appear late. Timeout/failure summaries enter metadata,
comments, reports, and possibly a repair prompt.

## Repair and merge

`_prepare_repair_prompt()` bounds and contextualizes the failure. `_process_existing_pr_card()`
monitors CI and applies merge/human-gate outcomes for an existing PR; it does not run the normal
model repair loop. Repair attempts for managed execution are capped by `_max_attempts()`.

`_automerge_eligible()` evaluates the GitHub auto-merge mode, configured label, and PR draft state.
It does not currently enforce release-policy human-gate fields. `_merge_pull_request()` intentionally
does not request branch deletion in the current tested behavior. Merge is an external irreversible
effect and must be recorded only after remote success.

## Verification map

- local completion/failure: `tests/test_services/test_autopilot.py`;
- argv versus shell policy: `tests/test_autopilot/test_verification.py`;
- PR open/wait/repair/reuse/merge/no-check behavior: service autopilot tests;
- worktree safety: autopilot plus `tests/test_swarm`.
