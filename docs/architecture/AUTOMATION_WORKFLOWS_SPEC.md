# Automation workflows technical specification

Status: **Implemented on `kevin/automation-workflows`**

This document specifies a local-first automation subsystem for OpenHarness and its `ohmo`
application. It is intentionally implementation-facing: every required behavior has a stable
identifier, an owning boundary, and verification evidence. The user-facing workflow and operator
commands are documented in the [Ohmo automation guide](../guides/OHMO_AUTOMATION.md).

## Problem statement

`ohmo` can receive admitted channel messages, run one model/tool loop, and reply to the originating
conversation. OpenHarness also has skills, hooks, plugin and MCP tools, cron turns, permissions,
and local persistence. Those primitives do not currently form a durable workflow system:

- skills explain how work should be performed but model selection is probabilistic;
- hooks observe a fixed set of runtime events and receive too little channel context to be a
  general message router;
- cron supplies a time trigger but not conditional multi-step orchestration;
- the gateway sends normal replies to the originating channel and exposes no generic cross-channel
  action;
- the in-memory channel bus has no restart recovery, workflow checkpoints, deduplication, or
  action-level retry history; and
- remote turns cannot answer an interactive permission prompt.

The required capability is a systematic process that reacts to an admitted event, applies
deterministic rules, optionally uses a named skill for human-like judgment, performs multiple
restricted actions, branches on results, records durable progress, and can safely resume or retry.

## Decision and alternatives

### Option A: compose existing skills, hooks, and plugin tools only

- **Approach:** put the procedure in a skill, use a prompt hook as the trigger, and let the model
  call plugin or MCP tools.
- **Advantages:** no new subsystem and fast for a one-off prototype.
- **Costs:** probabilistic activation, incomplete event context, no durable workflow state,
  inconsistent retries, and no systematic loop prevention.
- **Effort:** small per workflow, but repeated and fragile.

### Option B: add a local workflow coordinator around existing primitives

- **Approach:** normalize events, match trusted YAML rules, run durable typed steps, inject named
  skills into bounded agent steps, and reuse governed tools for effects.
- **Advantages:** deterministic activation and control flow while retaining agent judgment and the
  existing provider/tool ecosystem.
- **Costs:** a new persisted format and lifecycle owner; governed tool execution must become
  reusable outside provider-emitted tool calls.
- **Effort:** large, incrementally deliverable.

### Option C: delegate orchestration to an external product

- **Approach:** send events to Temporal, n8n, or a similar service and expose OpenHarness as one
  worker/action.
- **Advantages:** mature workflow durability and visual operations.
- **Costs:** contradicts the repository's local-first deployment, adds an operational dependency,
  and splits permissions and extension discovery across systems.
- **Effort:** medium implementation plus ongoing operations.

**Decision:** implement Option B. It matches the current local-first architecture, preserves the
provider-neutral agent loop, and gives extensions one systematic execution model. External engines
can be added later through event/action adapters rather than becoming a prerequisite.

## Design principles

1. **Rules decide when; skills describe how; actions perform effects; the runner owns state.**
2. **Admission precedes automation.** A channel adapter's sender, group, and mention policy runs
   before an event can trigger a workflow.
3. **Skill activation is explicit.** A rule names a skill; the model does not have to discover it.
4. **Instructions are not authority.** A skill cannot expand the workflow's allowed tools,
   destinations, paths, or approval policy.
5. **Deterministic work stays deterministic.** Known actions do not require a model turn.
6. **Every external effect is attributable.** Runs and steps have stable IDs and audit records.
7. **At-least-once delivery is made safe with idempotency.** Exactly-once external side effects are
   not claimed.
8. **Core remains reusable.** Generic definitions, matching, state, and running live under
   `src/openharness`; workspace, channel, and personal-memory adapters live under `ohmo`.
9. **Project content is not silently trusted.** Project automation is disabled unless explicitly
   enabled, matching the executable-project-plugin trust boundary.

## System overview

```text
Channel adapter / manual command / future schedule or webhook
                         |
                         v
               admitted AutomationEvent
                         |
                         v
              deterministic rule matcher
                         |
                         v
          durable run + idempotency reservation
                         |
          +--------------+----------------+
          |              |                |
          v              v                v
   condition step    agent step       action step
                     named skill      registered action
                     bounded tools    or governed tool
          |              |                |
          +--------------+----------------+
                         |
                         v
        checkpoint / retry / approval / audit / reply
```

The `ohmo` gateway publishes an automation event only after the adapter and bridge have accepted a
message. The automation service starts matching workflows without blocking the bridge from
consuming unrelated conversations. A definition chooses whether the normal assistant turn also
continues.

## Functional requirements

### Events and discovery

- **AUT-FR-001 — Normalized event.** Core defines a versioned `AutomationEvent` containing a stable
  ID, type, source, timestamp, actor, subject, JSON-safe payload, sanitized metadata, and an
  `automation_generated` marker.
- **AUT-FR-002 — Channel trigger.** `ohmo` converts every admitted channel message into a
  `channel.message` event with channel, chat, thread, sender, text, attachment descriptions, and
  platform message/event identifiers where available.
- **AUT-FR-003 — Manual trigger.** Operators can submit a JSON event or invoke one workflow through
  the CLI without a real channel SDK.
- **AUT-FR-004 — Trusted definition discovery.** `ohmo` loads `*.yaml` and `*.yml` from
  `<workspace>/automations/`. Definitions are data, parsed with `yaml.safe_load`, bounded in size,
  validated with Pydantic, and never evaluated as Python or shell.
- **AUT-FR-005 — Skill binding.** A workflow may explicitly name a discovered skill for an agent
  step. A `SKILL.md` alone never activates automation. Missing or disabled-for-model skills fail
  validation before the run starts. Normal skill-registry precedence resolves duplicate names
  deterministically, so automation uses the same unambiguous selected definition as an interactive
  runtime rather than inventing a second precedence rule.
- **AUT-FR-006 — Generic event shape.** Matching and running depend on event type and JSON paths,
  not Slack classes. Future cron, webhook, GitHub, email, or filesystem adapters can emit the same
  envelope without changing the runner.

### Matching and control flow

- **AUT-FR-010 — Deterministic source filter.** A trigger can constrain event type, channel,
  account, chat/thread, actor, and `automation_generated` state without a model call.
- **AUT-FR-011 — Safe conditions.** Conditions support `eq`, `ne`, `in`, `not_in`, `contains`,
  `starts_with`, `ends_with`, `glob`, `regex`, `exists`, and numeric comparison over bounded JSON
  paths. Groups support `all`, `any`, and `not`. Regex uses a documented safe subset with bounded
  pattern/input lengths; backreferences, lookarounds, and nested or repeated quantifiers are
  rejected before matching.
- **AUT-FR-012 — Priority and fan-out.** Matching definitions are ordered by descending priority
  then stable workflow ID. Each creates an independent run unless its deduplication reservation
  already exists.
- **AUT-FR-013 — Source continuation.** A workflow declares `source_behavior` as `continue`,
  `consume`, or `silent`. `continue` also runs the normal assistant turn, `consume` suppresses that
  turn but may acknowledge, and `silent` suppresses both the normal turn and automatic source reply.
- **AUT-FR-014 — Conditional steps.** Every step may have a deterministic `when` group referencing
  the event and completed step outputs. A false condition records `skipped`, not `failed`.
- **AUT-FR-015 — Data flow.** Step arguments use `${event...}`, `${run...}`, and
  `${steps.<id>.output...}` references. A whole-value reference preserves its JSON type; embedded
  references render as strings. Missing references fail the step before an action executes.
- **AUT-FR-016 — Step types.** Version 1 supports `action`, `agent`, and `approval` steps. Sequential
  declaration order is authoritative. Parallel branches and loops are not part of version 1.

### Actions and agent steps

- **AUT-FR-020 — Action registry.** Hosts register typed asynchronous actions by stable name. Each
  action validates input, returns a JSON-safe result, declares whether retries are safe, and owns
  validation of external destinations or namespaces.
- **AUT-FR-021 — Governed tool action.** A workflow can invoke an existing built-in, plugin, or MCP
  tool through a reusable governed executor that preserves schema validation, sensitive-path
  denial, permission rules, hooks, sandbox-aware effect routing, output bounds, and `ToolResult`
  normalization.
- **AUT-FR-022 — Restricted agent step.** An agent step loads the named skill content explicitly,
  runs in an isolated automation session, enforces step-specific model/turn/time limits, and exposes
  only the intersection of workflow-allowed and installed tools.
- **AUT-FR-023 — Structured agent output.** An agent step declares an object-shaped output schema.
  Later steps cannot consume its output until the final response parses as JSON and validates. An
  invalid response may use the step retry policy but never silently becomes an empty object.
- **AUT-FR-024 — Channel send action.** `ohmo` registers `channel.send`, accepting a configured
  channel, chat ID, content, optional thread/reply metadata, and media. The action publishes through
  the existing `MessageBus`; the workflow policy must allow the destination.
- **AUT-FR-025 — Knowledge upsert action.** `ohmo` registers `knowledge.upsert`, initially targeting
  the selected workspace's personal-memory backend through its schema/index helpers rather than raw
  file writes. The result returns the memory entry identity and path without exposing unrelated
  memory content.
- **AUT-FR-026 — Extensible actions.** Trusted `ohmo` workspace plugins can contribute action
  implementations through an explicit automation-action extension point. Project action code
  remains disabled unless project plugins are trusted.

### Durability, retries, and concurrency

- **AUT-FR-030 — Persistent definitions and state.** Definitions live under
  `<workspace>/automations/`; operational state lives under `<workspace>/automation/` so generated
  state is not mixed with user-authored rules.
- **AUT-FR-031 — Run state machine.** Runs use `pending`, `running`, `waiting_approval`, `completed`,
  `failed`, or `cancelled`. Steps use `pending`, `running`, `skipped`, `waiting_approval`,
  `completed`, or `failed`. Illegal transitions are rejected.
- **AUT-FR-032 — Atomic checkpoints.** A run is atomically replaced under an exclusive workflow
  lock after every state transition and action attempt. A process crash can repeat an in-flight
  retry-safe action but cannot erase completed step evidence.
- **AUT-FR-033 — Idempotent intake.** The store atomically reserves
  `(workflow_id, event_id)` before execution. Repeated platform deliveries return the existing run.
  Startup recovery can rebuild a corrupt or missing reservation index by scanning run files.
- **AUT-FR-034 — Action idempotency.** The runner supplies
  `<run_id>:<step_id>:<attempt>` plus a stable logical step key. Actions capable of server-side
  idempotency use the stable key. `channel.send` is deliberately non-retry-safe and records local
  queue acceptance, not remote delivery: the existing channel bus/adapter contract has no delivery
  acknowledgement, so a process or platform failure can still lose or duplicate a remote message.
  The system must not report such queue acceptance as exactly-once or confirmed delivery.
- **AUT-FR-035 — Retry and timeout.** Workflow defaults and step overrides define attempts,
  bounded exponential backoff, timeout, and retryable error categories. Validation, policy denial,
  and approval rejection are not retried.
- **AUT-FR-036 — Concurrency key.** A definition can render a concurrency key and choose `serialize`,
  `drop`, or `cancel_previous`. The service releases every acquired key during success, failure,
  and cancellation.
- **AUT-FR-037 — Recovery.** On service startup, `running` runs become `pending` recovery candidates;
  `waiting_approval` remains waiting; terminal runs remain unchanged. Recovery never reruns a
  completed step. If a crash left an attempted non-retry-safe action without a recorded result, the
  run fails with `outcome_unknown` and requires an explicit operator retry; it is not replayed
  automatically.
- **AUT-FR-038 — Loop prevention.** Messages emitted by `channel.send` carry automation origin
  metadata inside the host. Adapters also retain their existing bot/self-message suppression and
  platform message IDs because internal metadata is not guaranteed to survive an external channel
  round trip. Generated events do not trigger workflows unless a definition explicitly opts in. A
  per-run maximum step count, event ancestry depth, and repeated-platform-message reservation
  provide secondary bounds.

### Approval, operation, and observability

- **AUT-FR-040 — Durable approval.** An approval step records prompt, allowed approver IDs, expiry,
  resume position, and an explicit notification target or the admitted source conversation. The
  host delivers the request once with the run ID and approve/reject instructions. A run resumes only
  after an authenticated admitted actor approves it. `silent` workflows must configure an explicit
  approval target rather than implicitly notifying the source.
- **AUT-FR-041 — Approval commands.** `ohmo` supports `/automation approve <run-id>` and
  `/automation reject <run-id> [reason]` through the gateway and equivalent local CLI commands.
  The actor must match the step allowlist; normal remote-admin configuration cannot bypass it.
- **AUT-FR-042 — Management CLI.** `ohmo automation` supports `validate`, `list`, `show`, `test`,
  `run`, `runs`, `inspect`, `retry`, `cancel`, `approve`, and `reject`. Read commands redact secret
  references and bounded payload fields.
- **AUT-FR-043 — Dry-run matching.** `automation test` reports definition validation, source filter,
  condition outcomes, and rendered arguments without executing agents or actions.
- **AUT-FR-044 — Audit history.** Every run records definition revision, event identity, timestamps,
  step attempts, redacted inputs, bounded outputs, errors, approvals, and the final source behavior.
- **AUT-FR-045 — Logs and metrics.** Structured logs carry workflow, run, event, and step IDs. The
  service exposes counts for loaded/invalid definitions and active/waiting/failed runs through
  status output; external metrics export is not required in version 1.

## Non-functional requirements

- **AUT-NFR-001 — Security:** channel admission and workflow source policy are separate mandatory
  gates. Definitions cannot contain plaintext provider or channel credentials; actions receive
  resolved host capabilities rather than raw secrets in templates.
- **AUT-NFR-002 — Least authority:** unattended workflows use explicit action/tool and destination
  allowlists. They must not require global `full_auto` mode.
- **AUT-NFR-003 — Prompt-injection containment:** event text and prior step output remain untrusted
  data. They cannot alter step type, action name, policy, approval list, or tool allowlist through
  interpolation.
- **AUT-NFR-004 — Local-first:** normal operation requires no database server, message broker, or
  hosted workflow service.
- **AUT-NFR-005 — Bounded resources:** definition/event/output sizes, regex length, model turns,
  attempts, backoff, run duration, ancestry, and stored history have configured bounds.
- **AUT-NFR-006 — Async lifecycle:** channel intake does not synchronously wait for a workflow run;
  all service tasks have cancellation and cleanup owners.
- **AUT-NFR-007 — Compatibility:** unknown definition versions or step types are rejected with file
  and validation context. Version 1 fields are not silently reinterpreted.
- **AUT-NFR-008 — Offline tests:** unit and integration tests use fake agents/actions/channels and
  require no credentials, network calls, or real model API.
- **AUT-NFR-009 — Data handling:** persisted events omit raw SDK objects, tokens, headers, and
  arbitrary metadata. Logs and CLI views apply the repository's credential redaction rules.
- **AUT-NFR-010 — Current scale:** one local gateway process and tens of workflows are the target.
  Correct recovery and bounded queues matter more than distributed execution.

## Definition schema

The following example is normative for version 1 field names. Conditions use structured data rather
than an expression evaluator.

```yaml
version: 1
id: production-incident-routing
description: Classify production alerts, notify operations, and retain durable knowledge.
enabled: true
priority: 100
source_behavior: consume

trigger:
  event: channel.message
  source:
    channel: slack
    chat_ids: [C_PRODUCTION_ALERTS]
    actor_ids: [U_MONITORING_BOT]
    include_automation_generated: false

conditions:
  any:
    - path: event.payload.text
      op: regex
      value: '(?i)(critical|sev[ -]?1|production down)'
    - path: event.payload.labels
      op: contains
      value: production-incident

concurrency:
  key: '${event.source.channel}:${event.subject.chat_id}:${event.subject.thread_id}'
  policy: serialize

policy:
  allowed_actions: [channel.send, knowledge.upsert]
  allowed_tools: [slack_history, knowledge_search]
  channel_destinations:
    slack: [C_OPERATIONS]
  knowledge_namespaces: [incidents]

defaults:
  retry:
    attempts: 3
    backoff_seconds: [1, 5, 30]
  timeout_seconds: 120
  max_run_seconds: 604800

steps:
  - id: assess
    type: agent
    skill: production-incident-triage
    max_turns: 6
    allowed_tools: [slack_history, knowledge_search]
    output_schema:
      severity: {type: string, required: true}
      summary: {type: string, required: true}
      customer_impact: {type: boolean, required: true}
      knowledge: {type: string, required: true}

  - id: approval
    type: approval
    prompt: 'Approve escalation for ${steps.assess.output.summary}'
    approver_ids: [U_INCIDENT_COMMANDER]
    expires_seconds: 900
    when:
      path: steps.assess.output.severity
      op: in
      value: [sev1, sev2]

  - id: notify
    type: action
    action: channel.send
    with:
      channel: slack
      chat_id: C_OPERATIONS
      content: '${steps.assess.output.summary}'

  - id: remember
    type: action
    action: knowledge.upsert
    with:
      namespace: incidents
      title: '${steps.assess.output.summary}'
      content: '${steps.assess.output.knowledge}'
```

## Runtime data model

### `AutomationEvent`

| Field | Type | Contract |
| --- | --- | --- |
| `version` | integer | exactly `1` |
| `id` | string | stable within the source; bounded and filesystem-safe after hashing |
| `type` | string | namespaced event type such as `channel.message` |
| `occurred_at` | UTC datetime | source timestamp when reliable, otherwise receipt time |
| `source` | object | adapter type, channel/account, and instance identity |
| `actor` | object | admitted actor ID and optional display label |
| `subject` | object | chat/thread/message identifiers |
| `payload` | object | text and normalized attachment/event data |
| `metadata` | object | bounded allowlisted routing facts only |
| `automation_generated` | boolean | loop-prevention marker |
| `ancestry` | list | bounded parent event/run identifiers |

### `WorkflowRun`

| Field | Contract |
| --- | --- |
| `id` | sortable generated ID |
| `workflow_id` / `definition_revision` | immutable identity plus SHA-256 of the normalized validated definition used for this run |
| `event` | sanitized event snapshot |
| `status` | run state-machine value |
| `steps` | ordered step snapshots with attempts and bounded I/O |
| `current_step` | next or waiting step index |
| `context` | JSON-safe step output map used by templates |
| `concurrency_key` | rendered serialized-work key, if configured |
| `approval` | pending/resolved approval record, if any |
| timestamps | created, started, updated, completed |
| `error` | normalized category and redacted message |

### Local layout

```text
<workspace>/
├── automations/
│   └── *.yaml                 # user-authored trusted definitions
└── automation/
    ├── .lock                  # process/file transition lock
    ├── index.json             # workflow+event reservations and run summaries
    ├── runs/<run-id>.json     # authoritative run checkpoints
    └── archive/               # terminal runs moved by retention policy
```

The index is an optimization and reservation record. Run files are authoritative. If a crash occurs
between run and index replacements, startup recovery scans run files and reconstructs the index
under the lock. Atomic file replacement does not claim a cross-file transaction.

## Component ownership and interfaces

| Component | Owner | Input | Output / interface |
| --- | --- | --- | --- |
| Event and definition models | `openharness.automation.models` | untrusted JSON/YAML | validated immutable models |
| Definition loader | `openharness.automation.loader` | trusted roots | valid definitions plus per-file diagnostics |
| Matcher | `openharness.automation.matcher` | definition + event/context | traced boolean outcome |
| Template resolver | `openharness.automation.templates` | typed data + string/object template | rendered JSON-safe arguments |
| Store | `openharness.automation.store` | events and transitions | reservations, atomic run checkpoints, recovery |
| Action registry | `openharness.automation.actions` | typed action registrations | exact-name validated dispatch |
| Governed executor | extracted core tool lifecycle boundary | tool name/input/policy | normalized governed `ToolResult` |
| Runner | `openharness.automation.runner` | definition, event, injected executors | durable terminal/waiting run |
| Ohmo automation service | `ohmo.automation.service` | admitted messages and CLI requests | background run tasks/status |
| Channel and knowledge actions | `ohmo.automation.actions` | policy-allowed destinations/knowledge | bus publication and schema-aware memory upsert |
| Agent executor | `ohmo.automation.agent` | skill, event, limits, restricted tools | validated JSON object |
| Gateway integration | `ohmo/gateway/bridge.py`, `service.py` | admitted `InboundMessage` | event submission and source behavior |
| Operator commands | `ohmo/cli.py` and gateway command boundary | local/remote commands | validation, inspection, transitions |

Core modules must not import `ohmo`. Application capabilities are injected into the runner through
protocols or registries.

## Critical sequences

### Admitted channel message

```text
Adapter       Bridge       Automation service      Store       Runner        Actions
   | admitted   |                  |                  |            |              |
   |----------->|                  |                  |            |              |
   |            | normalize event |                  |            |              |
   |            |----------------->|                  |            |              |
   |            |                  | match definitions|            |              |
   |            |                  | reserve event--->|            |              |
   |            |                  |<------run ID------|            |              |
   |            |                  | start background------------->|              |
   |            |<--source behavior                 |               |              |
   |            | continue/consume                  | checkpoint--->|              |
   |            |                  |                |               |--execute---->|
   |            |                  |                |               |<---result----|
   |            |                  |                |<--checkpoint--|              |
```

The bridge remains the cancellation/serialization owner for normal conversation turns. Automation
runs have their own workflow/concurrency keys and do not mutate a cached conversational engine.

### Retry and approval

```text
running step
   |
   +-- validation or policy denial --> failed (no retry)
   |
   +-- retryable action failure --> checkpoint attempt --> bounded backoff --> retry
   |
   +-- approval step --> waiting_approval --> authenticated approve --> pending --> resume
   |                                      `-> reject/expire --> failed
   |
   `-- process crash --> startup recovery --> pending --> resume first incomplete step
```

## Permission and trust model

1. The channel adapter admits the sender before the event exists.
2. Trigger source filters restrict where a workflow can start.
3. Definition policy restricts action names, model tools, channel destinations, and knowledge
   namespaces.
4. Action input models validate rendered untrusted values.
5. Governed tool actions pass through hard sensitive-path denial, tool/path/command policy, hooks,
   and sandbox-aware implementations.
6. Agent steps see only a filtered tool registry. A skill or message cannot name an undisclosed
   tool into existence.
7. Approval steps require an explicit actor allowlist and durable state transition.
8. Project workflow discovery is off by default. Enabling it is an executable-authority decision,
   even when the file itself is declarative, because it can initiate external effects.

Workflow definitions may refer to secret aliases but never interpolate secret values into prompts,
logs, persisted run input, or output. The host resolves credentials inside an action implementation.

## Failure behavior

| Failure | Required behavior |
| --- | --- |
| Invalid definition | Exclude it, retain diagnostics, continue loading other files |
| Duplicate workflow or step ID | Reject every conflicting definition deterministically |
| Duplicate event delivery | Return existing run; do not start another |
| Missing template path | Fail step before executing an effect |
| Missing skill/action/tool | Fail validation or step with exact missing capability |
| Agent output invalid | Record bounded output; retry only within declared attempt limit |
| Policy denial | Record denial; never ask an unavailable remote permission prompt |
| Retry-safe transient failure | Checkpoint attempt and backoff before retry |
| Non-retry-safe uncertain effect | Fail with `outcome_unknown`; require operator retry decision |
| Process restart | Recover incomplete runs without repeating completed steps or automatically replaying an uncertain non-retry-safe effect |
| Outbound destination unavailable | Normalized action failure; no fallback to source destination |
| Approval expiry/rejection | Terminal failure with actor/time/reason audit |
| Definition changed during run | Existing run keeps its stored revision/snapshot |

## Operator experience

Representative commands:

```bash
ohmo automation validate
ohmo automation list
ohmo automation show production-incident-routing
ohmo automation test production-incident-routing --event event.json
ohmo automation run production-incident-routing --event event.json
ohmo automation runs --status failed
ohmo automation inspect RUN_ID
ohmo automation retry RUN_ID
ohmo automation cancel RUN_ID
ohmo automation approve RUN_ID
```

Gateway equivalents are limited to admitted, explicitly authorized approval/cancellation actions;
definition editing and arbitrary manual event submission remain local-only.

## Incremental delivery and commit gates

Each increment is independently reviewed, tested, committed, and pushed before work starts on the
next increment.

### Increment 0 — specification

- This specification and architecture index link.
- Documentation structural validation.
- Critical review for boundary, security, and testability gaps.

### Increment 1 — typed definitions, events, matching, and rendering

- `AutomationEvent`, definition/step/condition models, loader diagnostics, matcher traces, and safe
  templates.
- Unit tests for every operator, invalid/bounded input, duplicate IDs, unknown versions, and type-
  preserving interpolation.
- No side effects or gateway integration.

### Increment 2 — durable store and state machine

- Reservation index, run/step transitions, atomic checkpoints, index rebuild, recovery, retention
  hooks, and concurrency coordinator.
- Filesystem tests for duplicates, malformed files, crash-shaped partial state, cancellation, and
  every legal/illegal transition.

### Increment 3 — action registry and runner

- Typed host actions, sequential/conditional steps, retry/timeout, policy enforcement, audit
  records, and fake-agent/action integration tests.
- Extract or introduce the reusable governed tool executor before enabling arbitrary tool actions.

### Increment 4 — explicit skill agent steps

- Skill resolution, isolated automation runtime, filtered tool registry, structured output, model
  bounds, cleanup, and offline fake-provider integration tests.

### Increment 5 — `ohmo` actions and gateway end to end

- Workspace paths and service lifecycle, admitted channel events, `channel.send`,
  `knowledge.upsert`, source behavior, loop markers, and generic channel tests including Slack-shaped
  metadata.
- Fix any Slack configuration/admission mismatch that prevents the documented source policy from
  being enforced before claiming Slack support.

### Increment 6 — approvals and operator CLI

- Local management commands, dry-run trace, gateway approve/reject, actor authorization, expiry,
  recovery, redaction, and status counts.

### Increment 7 — final hardening

- Full Python baseline, documentation check, frontend typecheck only if protocol/launcher behavior
  changed, restart/recovery integration tests, threat-model review, compatibility/state docs,
  operator guide, and changelog.
- Independent critical diff review. All P0/blocker and P1/important findings must be addressed and
  reverified. P2 items are either fixed or recorded with rationale.

## Verification matrix

| Requirement area | Minimum evidence |
| --- | --- |
| Models and loader | `tests/test_automation/test_models.py`, `test_loader.py` |
| Matching/templates | `tests/test_automation/test_matcher.py`, `test_templates.py` |
| Store/recovery | `tests/test_automation/test_store.py` with temporary roots |
| Runner/retry/concurrency | `tests/test_automation/test_runner.py` using deterministic fakes |
| Governed tools | focused engine/permission/hook/tool tests plus automation integration |
| Skill agent | fake provider, filtered registry, invalid JSON, timeout and cleanup tests |
| Ohmo actions and gateway path | `tests/test_ohmo/test_automation_service.py` plus channel security tests |
| Approval and CLI | `tests/test_ohmo/test_automation_cli.py`, service actor-denial/restart tests |
| Persisted compatibility | state-format docs plus malformed/unknown-version tests |
| End-to-end | admitted Slack-shaped event → condition → skill/fake agent → cross-chat message + memory |
| Regression | `uv run ruff check src tests scripts`, `uv run pytest -q`, docs checker |

Live Slack or model credentials are not required to prove the implementation. Live validation may
supplement, but never replace, deterministic tests.

## Definition of done

The feature is complete only when all of the following are true:

1. Every `AUT-FR-*` and `AUT-NFR-*` item has source and test evidence or is explicitly removed by a
   reviewed specification amendment before implementation—not silently omitted.
2. A generic admitted channel event can trigger a deterministic rule without relying on a Slack-
   specific runner.
3. One workflow can explicitly execute a named skill, validate structured output, branch, send to a
   different configured channel/chat, and update personal knowledge.
4. Duplicate delivery, restart recovery, retry exhaustion, policy denial, loop prevention,
   cancellation, and approval authorization have deterministic coverage.
5. The default trust posture remains conservative: no implicit project workflow execution, no
   plaintext secrets in definitions/history, and no requirement for global `full_auto`.
6. Current architecture, extension, state, testing, threat-model, operator, and changelog documents
   describe the implemented behavior rather than this proposal alone.
7. The complete relevant test baseline passes.
8. A final severity-ranked review has no unresolved P0/blocker or P1/important findings.
9. Every delivery increment is committed and pushed before the next increment begins.

## Explicit version 1 non-goals

- Distributed or multi-host workflow workers.
- Exactly-once guarantees for external APIs that lack idempotency support.
- Arbitrary Python, JavaScript, Jinja, or shell evaluation in conditions/templates.
- Cyclic graphs, `foreach`, or parallel workflow branches.
- A browser-based workflow editor.
- Automatic activation from ordinary project `SKILL.md` frontmatter.
- A public inbound webhook server; the event protocol is designed to add one later.

These exclusions constrain implementation complexity without narrowing the requested core outcome:
conditional admitted-message processing, named human-like skill execution, multiple governed
actions, cross-channel delivery, knowledge updates, and durable systematic operation all remain
required.
