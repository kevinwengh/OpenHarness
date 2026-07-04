# Observability and health signals

OpenHarness currently relies on local logs, state files, stream events, registry/journal data, and
CLI status commands. It does not provide a unified metrics endpoint, trace system, or SLO model.

## Signal map

| Area | Signals | Owner |
| --- | --- | --- |
| Runtime/query | stream status/error/tool/usage events | engine and host renderer |
| Provider | retries, translated errors, usage | API clients |
| MCP | per-server pending/connected/failed status | `McpClientManager` |
| Terminal | backend ready/state/task snapshots and stderr | backend host + Ink frontend |
| ohmo gateway | PID, running/last-error state, log, channel status | `OhmoGatewayService` |
| Channels | adapter logs, manager status, queue sizes | channel manager/message bus |
| Cron | PID/log/history and job next/last run | cron scheduler/registry |
| Tasks/bridge | task records and output logs | managers |
| Autopilot | registry, JSONL journal, reports, PR/CI state, dashboard | `RepoAutopilotStore` |

## Correlation

Session IDs, task IDs, bridge session IDs, autopilot card IDs, channel/session keys, tool-use IDs,
and PR numbers exist, but there is no one correlation ID spanning prompt → provider → approval →
hook → tool → snapshot → channel delivery. When diagnosing, record the identifiers at every
boundary without copying secret payloads.

## Health versus readiness

- Process/PID exists: liveness hint only.
- Config/auth status: a source was found, not that credentials work.
- Dry-run: composition readiness, not network/model readiness.
- MCP connected: handshake/capability discovery succeeded, not that every tool call will succeed.
- Gateway started: process launched, not every channel authenticated.
- Verification passed: configured commands passed, not that untested behavior is correct.

## Operational gaps

- no queue/pool/task cardinality metrics export;
- no bounded runtime-pool eviction signal;
- no standard structured redacted audit trail;
- no latency/error SLOs or alert thresholds;
- no distributed tracing across external services;
- uneven log rotation and retention.

Add metrics only after defining owner, cardinality, redaction, and operational action. Useful first
metrics are active runtime sessions, inbound/outbound queue depth, oldest queued age, active tasks,
tool duration/error, provider retry/error, MCP connection failures, snapshot failures, scheduler lag,
and autopilot status duration.
