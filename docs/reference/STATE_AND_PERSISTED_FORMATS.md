# State and persisted-format catalog

This catalog identifies current durable formats, their owners, and recovery properties. “Atomic”
means readers see a complete old or new file; it does not mean several related files commit as one
transaction.

## Core user state

| State | Default path | Format | Write/concurrency | Version/migration |
| --- | --- | --- | --- | --- |
| Settings/profiles | `~/.openharness/settings.json` | Pydantic JSON | lock + atomic replace via `save_settings()` | compatibility normalization in loader; no global schema version |
| Credentials | `~/.openharness/credentials.json` or keyring | plaintext JSON / OS secret store | lock + atomic mode-0600 file | no formal schema version |
| Copilot auth | config root auth file | JSON | atomic replacement | client-owned shape |
| Core sessions | data `sessions/<project>-<hash>/` | snapshot JSON + Markdown export | each snapshot atomic; no session lock | no explicit version |
| Tasks | data `tasks/<id>.log` plus process records | framed text/log | append/output owner | process recovery is limited |
| Cron jobs | data `cron_jobs.json` | JSON array | lock + atomic read-modify-write | no explicit version |
| Feedback | data `feedback/feedback.log` | text/log | append/write path | none |
| Runtime logs | logs root | text | logging subsystem | retention operator-owned |

Path ownership is centralized in `src/openharness/config/paths.py`. Core sessions are implemented by
`services/session_storage.py` behind `SessionBackend`.

## Project state

| State | Path | Format | Owner |
| --- | --- | --- | --- |
| Project memory | discovered memory root | Markdown with frontmatter/index | `memory/manager.py`, `memory/schema.py` |
| Project skills | configured relative skill roots | `SKILL.md` | `skills/loader.py` |
| Project plugins | `.openharness/plugins` | manifest + content/code | `plugins/loader.py`; opt-in trust |
| Tool artifacts | data `tool_artifacts/` | UTF-8 text offloaded from oversized tool results | `engine/query.py::_tool_artifact_dir()` |
| Swarm team/mailboxes | `~/.openharness/teams/...` | JSON files/status | swarm lifecycle and mailbox |
| Worktrees | Git metadata + directories | Git | `swarm/worktree.py` |
| Autopilot | `.openharness/autopilot/` | JSON, JSONL, YAML, Markdown | `autopilot/service.py` |

Memory is the most explicitly versioned durable format: schema helpers and `memory/migrate.py` can
validate, dry-run, back up, and apply normalization. That policy does not automatically cover
sessions, plugins, cron, or autopilot.

## ohmo workspace

`ohmo/workspace.py` owns the root and helper paths:

| State | Format | Confidentiality / behavior |
| --- | --- | --- |
| `soul.md`, `identity.md`, `user.md`, `BOOTSTRAP.md` | Markdown | injected into personal prompt according to lifecycle |
| `memory/` and `MEMORY.md` | Markdown/frontmatter | lock + atomic entry/index updates |
| `skills/`, `plugins/` | instruction and extension trees | private workspace roots injected into runtime |
| `automations/*.yaml` | versioned declarative workflow definitions | bounded safe-YAML loading; user-authored configuration |
| `automation/runs/*.json`, `automation/index.json` | workflow checkpoints and reservation index | mode-0600 atomic writes under a shared lock; startup recovery rebuilds the index and classifies interrupted effects |
| `sessions/` | JSON snapshots + transcript export | latest, per-key latest, and named files written atomically one at a time |
| `attachments/` | arbitrary media | copied/downloaded content; operator retention |
| `groups/` | JSON records | managed-group metadata |
| `gateway.json` | JSON | contains channel credentials in plaintext |
| gateway PID/state/restart notice | text/JSON | service coordination; ordinary writes |
| `logs/` | text | provider/channel/process diagnostics |

The same payload can be written to workspace-global latest, session-key latest, and named session
files. A crash between replacements can leave the pointers at different revisions.

## Autopilot formats

| File | Format and owner | Contract |
| --- | --- | --- |
| `registry.json` | `RepoAutopilotRegistry`, version currently `1` | task cards and statuses |
| `repo_journal.jsonl` | one `RepoJournalEntry` per line | append-only activity record |
| `active_repo_context.md` | rendered Markdown | prompt-facing current focus |
| `autopilot_policy.yaml` | policy mapping | intake, execution, GitHub, repair controls |
| `verification_policy.yaml` | command/gate mapping | commands; shell needs explicit opt-in |
| `release_policy.yaml` | release/merge mapping | declared human/revert intent; current service does not enforce these fields |
| `runs/` | Markdown reports | agent, verification, CI, and failure evidence |
| `docs/autopilot/snapshot.json` | dashboard projection | potentially publishable generated state |

`RepoAutopilotStore._ensure_layout()`, `_load_registry()`, `_save_registry()`, `append_journal()`,
and `export_dashboard()` are the owning implementation boundaries.

## Bridge and background coordination

- Bridge output: data root `bridge/<session-id>.log`, written by
  `BridgeSessionManager._copy_output()`.
- Swarm mailboxes: one JSON file per message, protected by exclusive file locks and temp/rename.
- Permission synchronization: request/resolution JSON files with locked transitions.
- Task output: append-only local logs; active process handles are not durable.
- Autodream locks: PID/timestamp files used for local process exclusion, not distributed leases.

## Atomicity and locking rules

`utils/fs.py::atomic_write_text()` uses a same-directory temporary file, flush, `fsync`, mode
application, and `os.replace()`. `utils/file_lock.py::exclusive_file_lock()` uses `fcntl` on POSIX
and `msvcrt` on Windows.

Use both for shared read-modify-write state. Atomic replacement alone is appropriate only where a
single-writer convention is enforced elsewhere. Neither primitive provides a distributed lease,
multi-file transaction, or external-side-effect rollback.

## Compatibility status

| Format family | Current policy |
| --- | --- |
| Memory | explicit schema/migration support |
| Autopilot registry | version field exists; broad migration policy not documented |
| Settings | compatibility loader behavior; no external version window |
| Sessions/tool metadata | sanitization and defaults; no schema version |
| Plugin Python API/manifests | validation but no formal semantic-version policy |
| Terminal OHJSON | typed on both sides but unversioned |
| Channel/gateway config | Pydantic compatibility models; adapter expectations can diverge |
| Automation definitions/runs | definition version `1`; strict validation and embedded definition snapshots; no downgrade support |

See [Compatibility policy](../COMPATIBILITY.md) for what maintainers should promise before changing
a format.

## Backup and recovery

1. Stop gateway, scheduler, and active mutating workers.
2. Record application version and effective root paths.
3. Copy core config/data/log roots, project `.openharness`, and the ohmo workspace as applicable.
4. Back up external keyring/CLI credentials separately.
5. Restore into isolated roots and run read-only status/list commands first.
6. Treat corrupt/legacy state as a migration case; do not silently overwrite the only copy.

There is no global consistent-snapshot transaction across all roots.
