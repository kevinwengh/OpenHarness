# Product boundaries and deployment shapes

**Confidence: Observed unless marked otherwise.** The repository ships a reusable OpenHarness
runtime and an `ohmo` application built on it. It also ships two frontend shapes: a local terminal
and channel gateways. Keeping these dimensions separate allows reuse, but current source contains
some boundary debt.

## Intended dependency direction

```text
CLI / print / terminal hosts ─┐
                             ├──> openharness runtime and contracts
ohmo local CLI / gateway ────┘

openharness core ──X──> ohmo application policy
```

`openharness` owns provider-neutral messages, clients, agent/tool execution, permissions, hooks,
skills/plugins, MCP, session protocols, channels, and reusable UIs. `ohmo` owns a personal workspace,
identity/profile prompts, personal memory, gateway configuration, conversation routing, managed
group policy, attachments, notifications, and per-conversation runtime reuse.

## Deployment shapes

| Shape | Process topology | Runtime lifetime | Durable state | Appropriate use |
| --- | --- | --- | --- | --- |
| `oh -p` | One Python process | One prompt/query | Core settings/session paths | Scripts and CI-friendly headless calls |
| `oh` React terminal | Parent Python launcher → Ink process → backend Python child | Interactive terminal session | Core settings/sessions/memory | Local coding session |
| Textual/fallback UI | One Python process | Interactive terminal session | Core settings/sessions/memory | Environments without React path |
| Task worker | Headless Python worker | Task/request lifetime | Task output and sessions | Background delegated work |
| `ohmo` local | Python application over shared runtime | Local interactive invocation | ohmo workspace and session backend | Personal workspace use |
| `ohmo` gateway | Channel adapters + router + runtime pool in a service process | Long-lived, one bundle per conversation key | ohmo sessions, memory, config, logs | Multi-channel personal assistant |
| Autopilot | Repository service plus generated dashboard | Long-running/task-driven | `.openharness/autopilot`, published snapshot | Repository task intake and monitoring |

The React terminal is not a remote web architecture. The Ink process inherits the user's terminal
and spawns a backend child connected by newline-delimited JSON over pipes. See
[Frontend/backend IPC](frontend_backend_ipc.md).

## ohmo composition

`OhmoSessionRuntimePool` calls the same `build_runtime()` used by core hosts, injecting:

- an `OhmoSessionBackend` scoped to the workspace;
- personal skill and plugin roots;
- an ohmo memory command backend;
- a system prompt built from workspace identity/profile/memory;
- gateway-specific tools and request context;
- the selected provider profile and optional model/turn overrides.

Project memory is disabled for gateway bundles so personal workspace memory has a clear owner. A
conversation key selects or creates a bundle; snapshots allow lazy reconstruction after restart.
The gateway converts normalized channel input into engine messages and converts stream events back
into progress, media, error, and final outbound updates.

## Routing identity

Conversation identity is derived from channel metadata such as account, chat, thread/topic, and
explicit override. The key is both a continuity boundary and a concurrency boundary:

- messages with the same key share history, tools, system prompt refresh, and snapshot target;
- messages with different keys receive distinct `RuntimeBundle` instances;
- changing a key can split expected context; collapsing keys can leak context between conversations.

Route derivation is therefore part of the data-isolation contract, not just a convenience string.
New channels must test direct messages, groups, threads/topics, multiple accounts, and override
authorization.

## Decisions and trade-offs

### D1 — application composition instead of forking the engine

**Decision.** `ohmo` injects workspace/persistence/prompt behavior into the reusable runtime.

**Benefits.** Provider clients, permissions, tool loop, extensions, compaction, and stream events
stay consistent across local coding and personal-agent use.

**Costs.** The runtime needs explicit injection seams. Application-specific shortcuts can leak into
core when a seam is missing.

### D2 — runtime per conversation key

**Decision.** A long-lived gateway caches one bundle per active key.

**Benefits.** Conversation history and provider/tool state stay warm and isolated by key.

**Costs.** Memory/resource use grows with active keys; the current pool has no eviction or capacity
limit. Same-key concurrency also needs an explicit serialization policy.

### D3 — local filesystem workspace

**Decision.** ohmo identity, memory, sessions, attachments, logs, and gateway config are colocated in
one workspace root.

**Benefits.** Backup, inspection, and portability are straightforward.

**Costs.** Workspace permissions become the main isolation boundary, and multi-host gateway
deployment needs external coordination not supplied by the current design.

### D4 — normalized channel adapter contract

**Decision.** Channel-specific SDK events become `InboundMessage`/`OutboundMessage` around a shared
bus/router.

**Benefits.** Runtime and routing logic do not fork for every SDK.

**Costs.** Rich platform features can be lost or forced into metadata/media escape hatches. Adapter
tests must cover authorization, mentions, threading, size limits, and formatting.

## Boundary debt

The intended direction is `ohmo` → `openharness`, but core currently has optional reverse imports
for application-specific attachment roots, managed Feishu group lookup, and cron
notification/config integration. These imports make standalone core installation and testing less
independent and should not be copied as a pattern.

The preferred repair is not to move all application behavior into core. Core should define narrow
protocols or callbacks for media-root resolution, group policy, and notification delivery; `ohmo`
should register adapters at composition time. Completion criteria are tracked in the
[improvement backlog](../developer/IMPROVEMENTS.md#p1-remove-reverse-dependencies-from-core-into-ohmo).

## Current limitations

- The gateway runtime pool is process-local, unbounded, and lacks idle eviction.
- Same-conversation concurrency is not enforced by a per-key lock/queue in the pool.
- Enabling Docker sandboxing for multiple cached bundles would share one module-global sandbox slot;
  the current sandbox lifecycle is not pool-safe.
- The in-memory message bus does not survive process death or provide broker-grade backpressure.
- Workspace/session formats do not have a comprehensive external compatibility policy.
- Channel feature parity varies; normalized messages cannot automatically preserve every platform
  capability.
- Reverse core-to-ohmo imports weaken reuse and optional-installation guarantees.
- Multi-host active/active gateway operation, distributed leases, and shared session consistency are
  not defined.
- Operational scale, latency, and queue limits are not benchmarked or stated as service objectives.

## Future improvements

These are **proposed**:

1. Replace every reverse import with a core-owned protocol and ohmo adapter.
2. Add bounded, observable runtime-pool lifecycle with per-key serialization, idle eviction, and
   graceful snapshot/close.
3. Define route-key schemas and migration behavior so channel adapter changes do not silently split
   histories.
4. Add gateway health metrics for active sessions, queue depth, oldest request, provider failures,
   snapshot failures, and channel delivery failures.
5. Define a deployment profile: single-process/local-files first, then document what must change
   before multi-process or multi-host use.
6. Add contract tests shared by every channel adapter for identity, threading, authorization,
   attachments, and outbound failure handling.

## Change checklist

- Put reusable contracts in `src/openharness`; put personal workspace/channel policy in `ohmo`.
- Trace changes through local CLI, terminal/backend host, print mode, task workers, and gateway hosts.
- Treat session-key derivation as an isolation and compatibility contract.
- Give every cached runtime, queue, channel task, and external client a cleanup owner.
- Test standalone core behavior without importing or initializing `ohmo`.
