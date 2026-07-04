# Cron scheduler operations

OpenHarness cron is a local persistent scheduler, not a distributed exactly-once service.
`services/cron.py` owns job definitions and locked updates;
`services/cron_scheduler.py` owns the detached scheduler process, due-job polling, execution,
history, PID/log state, and optional ohmo notification integration.

## Manage jobs

```bash
oh cron list
oh cron status
oh cron history --limit 20
```

Model tools `cron_create`, `cron_list`, `cron_delete`, and `cron_toggle` use the same registry.
There is no `oh cron add` CLI command today. Create general jobs through `cron_create`, or install
the two repository-autopilot jobs with `oh autopilot install-cron --cwd /repo`.
`remote_trigger` records notification intent for supported execution paths; it is not a generic
remote queue.

Job mutations hold `exclusive_file_lock()` around load-modify-save and write the registry
atomically. The scheduler still needs one logical process owner; multiple schedulers can race around
due-time execution even if registry writes are valid.

## Start and verify

```bash
oh cron start
oh cron status
```

Verify the PID belongs to the expected installation/user, log/state paths are writable, the next-run
time is correct for its timezone, and the detached environment contains required PATH/provider
credentials. Use a harmless one-time/short test job before relying on an eight-hour schedule.

## Execution semantics

The scheduler polls definitions, launches a command or generated agent workflow when due, records
history, and advances schedule metadata. Machine sleep, process death, clock changes, and a crash
between launch and state update can produce delayed, missed, or repeated effects. Jobs should be
idempotent or carry their own deduplication key where external mutation matters.

## Notifications

Feishu direct-message notification is the implemented proactive ohmo target. It loads ohmo gateway
configuration and credentials outside the normal request/reply bridge. Missing SDK/config or API
errors do not retroactively undo job execution. Always preserve local history/log evidence even when
notification delivery fails.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Scheduler not running | PID ownership, stale PID, executable path, logs |
| Job never fires | enabled flag, cron expression/timezone, next-run, machine wakefulness |
| Job starts but model fails | detached environment, profile, credentials, cwd, max turns |
| Duplicate side effect | job idempotency and crash window around launch/update |
| Notification missing | local job result first, then ohmo workspace and Feishu config |

Stop the scheduler before editing/deleting registry files manually or restoring a backup.
