# Recovery, idempotency, and dashboard

## Recovery sources

Autopilot has no single transaction across local files, Git, model side effects, and GitHub. Recover
by reconciling:

1. registry card/status/metadata;
2. journal entries;
3. active context;
4. run and verification reports;
5. worktree, branch, commits, and remote;
6. PR/comments/checks/merge state;
7. scheduler logs/history if invoked by cron.

Prefer external truth for whether a PR exists or merged and Git truth for branch contents. Never
overwrite the only worktree or registry copy while diagnosing.

## Idempotency mechanisms

- source reference then fingerprint deduplication during intake;
- stable card/branch naming;
- open-PR lookup and reuse;
- recognition of existing branch progress;
- attempt and repair-round bounds;
- journal/report append/update evidence;
- merge eligibility checked from current PR state.

These controls reduce duplication but do not create exactly-once semantics. Two scheduler processes
or a crash at an external side-effect boundary can still duplicate comments, pushes, or work.

## Failure playbook

| Evidence | Interpretation / action |
| --- | --- |
| `running` but no process | interrupted attempt; inspect reports/branch before retry |
| `waiting_ci` with merged PR | reconcile card to remote merged state, preserve audit note |
| `failed` with useful branch | do not delete; hand off or requeue with explicit attempt policy |
| journal tail malformed | preserve file, recover valid preceding JSONL, record repair |
| registry invalid | stop automation, copy directory, validate version/cards before rewrite |
| dashboard stale | regenerate from store; never edit snapshot to “fix” state |

## Dashboard contract

`_build_dashboard_snapshot()` emits generated time, counts, columns/cards, focus, and journal.
`_serialize_card()` converts Pydantic/nested metadata into JSON-safe values. The Vite dashboard fetches
`snapshot.json` without a backend.

Publishing the dashboard can disclose issue/PR text, labels, source references, notes, CI/failure
summaries, and timing. Inspect generated content and repository visibility before Pages publication.

## Change checklist

- preserve registry version and old fixtures;
- test corrupt/missing files and partially existing branches/PRs;
- keep comments/PR creation idempotent;
- ensure terminal statuses retain report/remote identity;
- rebuild dashboard from authoritative state;
- verify scheduled concurrent operation assumptions explicitly.
