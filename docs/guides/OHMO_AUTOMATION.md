# Ohmo automation workflows

Ohmo automation turns admitted channel messages or manual JSON events into durable, conditional
multi-step work. Rules decide when a workflow starts, a named skill can provide bounded human-like
judgment, and typed actions perform effects such as posting to another chat or updating personal
knowledge.

This is separate from `oh cron`: cron supplies time-based prompts, while automation reacts to
generic events and checkpoints every step.

## Trust and safety model

- Channel adapters apply sender/group admission before a `channel.message` event exists.
- Workflow source filters and conditions are a second gate.
- `policy.allowed_actions`, `allowed_tools`, `channel_destinations`, and
  `knowledge_namespaces` are exact capability lists. Skill text and message content cannot expand
  them.
- Agent steps load the named skill explicitly, receive only their filtered tools, have turn/time
  bounds, and must return the declared JSON object.
- `channel.send` can attach only files already under the selected Ohmo workspace's `attachments/`
  directory. `knowledge.upsert` writes through the personal-memory schema and index.
- User/workspace plugins are executable trusted code. Project plugins remain disabled unless
  `allow_project_plugins` is enabled.
- External message delivery is at-least-once when a platform has no idempotency API. An interrupted
  non-retry-safe effect is recorded as `outcome_unknown` and is not replayed automatically.

## Files and lifecycle

Definitions are safe, strict YAML files under `<workspace>/automations/*.yaml`. Generated state is
separate under `<workspace>/automation/`; do not edit run JSON while the gateway is active.

The gateway loads definitions and resumes safe pending work at startup. Invalid definitions and
missing actions/skills are logged and excluded. A matched workflow can set:

- `continue`: run in the background and also let the normal assistant answer;
- `consume`: suppress the normal assistant turn;
- `silent`: suppress the normal turn and automatic source reply.

## Start from the repository example

Replace the example Slack IDs and approver ID before enabling it:

```bash
mkdir -p ~/.ohmo/automations ~/.ohmo/skills/incident-triage
cp examples/automation/incident-routing.yaml ~/.ohmo/automations/
cp examples/automation/incident-triage/SKILL.md ~/.ohmo/skills/incident-triage/
ohmo automation validate
ohmo gateway restart
```

The example accepts `channel.message` events from `C_ALERTS`, asks the named skill for structured
incident judgment, optionally waits for `U_INCIDENT_COMMANDER`, posts to `C_OPERATIONS`, and upserts
the result into the `incidents` personal-knowledge namespace.

## Validate and dry-run without effects

`validate` performs schema and installed-capability preflight. `test` evaluates source/condition
traces and renders currently available action arguments without invoking a model or action:

```bash
ohmo automation validate --workspace ~/.ohmo
ohmo automation list --workspace ~/.ohmo
ohmo automation show production-incident-routing --workspace ~/.ohmo
ohmo automation test production-incident-routing \
  --event examples/automation/slack-event.json \
  --workspace ~/.ohmo
```

Later-step templates that depend on earlier outputs appear as render errors in dry-run output
because no step executes.

## Manual event submission

Use `run` for an exact workflow and a version-1 JSON event:

```bash
ohmo automation run production-incident-routing \
  --event examples/automation/slack-event.json \
  --workspace ~/.ohmo \
  --cwd /path/to/project
```

This local command executes the workflow and prints any `channel.send` messages queued on its local
in-process bus; it does not connect channel SDKs. Use the running gateway for real channel delivery.
Knowledge and other local actions do execute. Reusing the same workflow/event ID returns the
existing run rather than repeating it.

## Inspect and operate runs

```bash
ohmo automation runs --workspace ~/.ohmo
ohmo automation runs --status waiting_approval --workspace ~/.ohmo
ohmo automation inspect RUN_ID --workspace ~/.ohmo
ohmo automation cancel RUN_ID --reason "superseded" --workspace ~/.ohmo
ohmo automation retry RUN_ID --workspace ~/.ohmo
ohmo automation retry RUN_ID --allow-unknown-outcome --workspace ~/.ohmo
```

`inspect` bounds large strings and redacts credential-shaped fields and common token formats.
`--allow-unknown-outcome` is deliberately explicit because an external effect may already have
happened.

## Approvals

An approval request contains its run ID and commands. Through an admitted channel, the sender ID
must exactly match `approver_ids`:

```text
/automation approve RUN_ID
/automation reject RUN_ID duplicate request
```

Remote-admin configuration cannot bypass that per-step actor list. Local equivalents also require
an explicit actor identity:

```bash
ohmo automation approve RUN_ID --actor U_INCIDENT_COMMANDER --workspace ~/.ohmo
ohmo automation reject RUN_ID --actor U_INCIDENT_COMMANDER \
  --reason "not an incident" --workspace ~/.ohmo
```

Approval requests are durably marked after local publication so ordinary restarts do not resend
them. A crash in the narrow publish-before-checkpoint window can still duplicate a request, so the
run ID is the stable operator reference.

## Definition constraints

Version 1 is intentionally sequential: `action`, `agent`, and `approval` steps, with optional
structured `when` conditions. It does not evaluate Python, shell, Jinja, loops, or arbitrary
expressions. See the normative
[automation workflow specification](../architecture/AUTOMATION_WORKFLOWS_SPEC.md) for every field,
transition, bound, and failure rule.
