# Operations index

These runbooks cover long-lived or stateful operation. They complement user guides by emphasizing
health evidence, recovery, and failure ownership.

| Service/workflow | Runbook |
| --- | --- |
| ohmo channel gateway | [Gateway operations](OHMO_GATEWAY.md) |
| cron scheduler and recurring jobs | [Cron operations](CRON_SCHEDULER.md) |
| repository autopilot | [Autopilot operations](AUTOPILOT.md) |
| backups, restore, and upgrades | [Backup and recovery](BACKUP_RESTORE_AND_UPGRADE.md) |
| logs and health signals | [Observability](OBSERVABILITY.md) |

The current deployment model is local/single-host. File locks, PID files, in-memory queues, and
process-local runtime pools do not provide multi-host coordination.
