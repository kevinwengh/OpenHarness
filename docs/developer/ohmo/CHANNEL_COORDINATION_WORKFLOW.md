# How ohmo channels are coordinated

The ohmo gateway can connect several chat platforms at once, but it is not one shared group chat or
one engine receiving every user's messages. Coordination means that adapters normalize platform
events onto one in-memory bus, an ohmo bridge authorizes and routes each event to a conversation
runtime, and one dispatcher sends resulting updates back through the originating adapter.

This document follows the complete workflow and makes the cross-channel sharing and isolation
boundaries explicit.

## Component ownership

| Component | Owner | Responsibility |
| --- | --- | --- |
| Channel config schema | `src/openharness/config/schema.py` | Typed credentials, enable flags, sender allowlists, adapter options |
| Adapter | `src/openharness/channels/impl/<channel>.py` | Connect SDK/transport, normalize inbound events, upload/send outbound content |
| Base channel | `src/openharness/channels/impl/base.py` | Common `allow_from` check and `InboundMessage` publication |
| Channel manager | `src/openharness/channels/impl/manager.py` | Construct enabled adapters, start/stop them, dispatch outbound messages |
| Message bus | `src/openharness/channels/bus/queue.py` | One inbound and one outbound `asyncio.Queue` |
| Gateway config adapter | `ohmo/gateway/config.py` | Project `gateway.json` into core channel config models |
| Gateway service | `ohmo/gateway/service.py` | Own bus, manager, bridge, runtime pool, process state, heartbeat, shutdown/restart |
| Router | `ohmo/gateway/router.py` | Convert channel/chat/thread/sender metadata into a conversation key |
| Bridge | `ohmo/gateway/bridge.py` | Additional admission, control commands, same-key cancellation, progress/final publication |
| Runtime pool | `ohmo/gateway/runtime.py` | Build/reuse one OpenHarness runtime per conversation key, run commands/turns, save snapshots |
| Session backend | `ohmo/session_storage.py` | Persist sanitized history and key-specific latest pointers |

The core `ChannelBridge` in `src/openharness/channels/adapter.py` is a simpler one-engine adapter.
The production ohmo gateway uses `OhmoGatewayBridge` instead because it needs keyed runtimes,
workspace persistence, command security, media, progress, and cancellation.

## Startup and service topology

`OhmoGatewayService.__init__()` performs the composition:

1. resolve the gateway cwd and change the process cwd;
2. initialize the selected ohmo workspace and export `OHMO_WORKSPACE`;
3. load `<workspace>/gateway.json`;
4. convert recognized enabled-channel dictionaries into core typed configs;
5. create one `MessageBus` shared by all adapters;
6. create one `ChannelManager` over that bus;
7. create one `OhmoSessionRuntimePool` for the workspace/default cwd; and
8. create one `OhmoGatewayBridge` connecting inbound bus traffic to the runtime pool.

`run_foreground()` then starts these concurrent service tasks:

```text
gateway process
├── bridge task: consume normalized inbound messages
├── channel-manager task
│   ├── one long-running start task per enabled adapter
│   └── one outbound-dispatch task
├── gateway-state heartbeat every five seconds
└── optional delayed restart-notice task
```

The gateway writes PID and state files before channel authentication completes. `gateway start`
therefore proves process spawn, not readiness of every adapter. Individual adapter startup errors
are caught, saved as `last_error`, and logged; they do not deliberately terminate other adapters.

## Configuration projection

`GatewayConfig` stores:

- one shared `provider_profile`;
- `enabled_channels`;
- global `send_progress` and `send_tool_hints` flags;
- remote-administration controls; and
- a free-form configuration dictionary per channel.

`build_channel_manager_config()` starts from the core `Config` model and enables only names known to
`ChannelConfigs`. Unknown names are skipped. Pydantic validation occurs when each recognized
channel model is copied.

The guided `ohmo config` wizard currently covers Telegram, Slack, Discord, and Feishu/Lark. Other
registered adapters require manual fields and should not be inferred to have the same maturity.
See the [channel capability matrix](../../reference/CHANNELS.md).

Three persisted gateway fields are not active controls today: `session_routing`, `permission_mode`,
and `sandbox_enabled`. The router uses its fixed key algorithm, while permissions/sandbox come from
effective OpenHarness settings.

## Complete inbound-to-outbound workflow

### 1. A platform adapter receives an event

Each adapter owns its SDK/transport loop, reconnection details, platform event parsing, mention or
room behavior, and media download. It normalizes useful platform values into:

```text
InboundMessage(
  channel,
  sender_id,
  chat_id,
  content,
  media,
  metadata,
  session_key_override,
)
```

Thread IDs, chat type, message IDs, mentions, filenames, and platform-specific sender forms are
carried in `metadata` where implemented. This metadata is not cosmetic: router isolation, Feishu
policy, reply threading, group commands, and attachment handling depend on it.

### 2. Sender admission happens before the bus

Adapters normally call `BaseChannel._handle_message()`. The base policy is:

- empty `allow_from`: deny everyone;
- `allow_from: ["*"]`: explicitly allow everyone;
- otherwise match the full sender string or one `|`-separated identity component.

Adapter-specific filters can happen before that call. Mention/group rules are not a substitute for
the allowlist: “the bot was mentioned” answers when to wake it, while `allow_from` answers who may
reach the runtime.

Accepted messages are placed on the shared inbound `asyncio.Queue`. The queue is process-local,
unbounded by configuration, and not durable; a gateway restart loses queued messages.

### 3. The bridge applies ohmo-specific policy

`OhmoGatewayBridge.run()` consumes inbound messages. It applies an additional Feishu group policy:

| Policy | Feishu group admitted when |
| --- | --- |
| `open` | every base-admitted group message |
| `mention` | metadata says the bot was mentioned |
| `managed` | the group exists in ohmo's managed-group registry |
| `managed_or_mention` | either managed or mentioned |

Unknown values normalize to `managed_or_mention`. Non-Feishu and non-group traffic bypasses this
extra bridge policy.

### 4. The router derives a conversation key

Unless an adapter supplied an explicit override, `session_key_for_message()` creates:

| Context | Key |
| --- | --- |
| Private chat | `channel:chat_id` |
| Private thread | `channel:chat_id:thread_id` |
| Shared chat | `channel:chat_id:sender_id` |
| Shared thread | `channel:chat_id:thread_id:sender_id` |

The router recognizes `thread_id`, `thread_ts`, then `message_thread_id`. Shared-chat sender identity
prevents two people in one room from receiving the same model history. Private keys intentionally
retain the older channel/chat shape for compatibility.

The channel name is always present in normal generated keys. The same human talking to ohmo in
Telegram and Slack therefore gets two conversation histories unless an adapter deliberately uses
the same explicit override.

### 5. Bridge-owned control commands run before the runtime

Three paths are special:

- exact `/stop` cancels the active task for this conversation key and returns a status message;
- exact `/restart` cancels that task, sends a restart notice, and asks the whole gateway service to
  restart; and
- `/group ...` is transformed only for a Feishu private chat into a constrained internal agent
  prompt.

These controls are intercepted before the shared slash-command authorization logic. Any sender who
already passed adapter and group admission can invoke `/stop` for their key and `/restart` for the
whole gateway. Remote-admin command allowlists do not add another check to these bridge controls.

### 6. One active task is tracked per key

Before starting a normal message, the bridge looks for an older task with the same key. It cancels
the old task, optionally emits a replacement notice, and waits up to three seconds through
`asyncio.shield()` before creating the new task.

Different keys run concurrently. The bridge itself returns quickly to the inbound queue after task
creation. There are two qualifications:

- the bounded cancellation wait temporarily delays the bridge from dequeuing other inbound
  messages; and
- timeout does not prove nested provider/tool work has stopped, so a cancellation-resistant old
  operation can overlap the new task against the same cached bundle.

The runtime pool intentionally has no same-key lock; it relies on bridge cancellation as its
serialization boundary.

### 7. The runtime pool selects cwd and bundle

The pool checks managed-group metadata for a valid cwd; otherwise it uses the gateway default. It
then obtains a bundle by conversation key:

1. reuse the cached bundle when its cwd still matches;
2. close/evict it when its cwd changed;
3. load only the ohmo snapshot indexed by the exact key;
4. build a core `RuntimeBundle` with ohmo persona, personal memory, workspace extensions and
   session backend, with normal project-memory recall disabled;
5. sanitize/restore messages and safe tool metadata;
6. start and cache the bundle.

Different keys use different engines/messages, but the bundles share workspace files, gateway
profile selection, process-global task services, and whatever external state their tools touch.

### 8. Command versus model-turn routing

Text without media is checked against the core command registry and then skill slash commands.
Attachments deliberately bypass command parsing, so `/memory list` plus a file is treated as model
input.

For a command, gateway authorization checks:

1. commands marked `remote_invocable=True` are allowed;
2. a local-only command is allowed only when it advertises remote-admin opt-in, gateway remote
   administration is enabled, and its normalized name is in the configured allowlist;
3. gateway `/provider` and `/model` are intercepted to update gateway/profile state correctly; and
4. a command result can respond immediately, refresh the bundle, submit an internal prompt, or
   continue a pending tool loop.

Ordinary messages are converted to core conversation messages, including normalized attachment
blocks, and submitted through the shared `QueryEngine`.

### 9. The shared engine streams events

The engine performs the same provider/tool loop used by `oh`: permissions, hooks, sandbox routing,
MCP/plugin tools, context compaction, usage, session-memory updates, optional extraction, and
auto-dream scheduling.

The pool converts events for channel use:

| Engine event | Gateway update |
| --- | --- |
| Assistant text delta | Accumulate silently for final reply |
| Status | Optional progress message |
| Compaction progress | Optional localized progress message |
| Tool start | Optional concise tool hint |
| Tool completion with files/media | Immediate media update |
| Error | Immediate error update |
| Assistant turn complete | Final-text fallback when no deltas were collected |

If a provider rejects image input, the pool strips image blocks from history and retries the
pending turn once. Group-tool context is installed only for the internal group workflow and removed
before persistence.

### 10. The pool saves a sanitized snapshot

After commands and model turns, the pool writes through `OhmoSessionBackend`:

- one `session-<session-id>.json` history file;
- workspace `latest.json`; and
- when a channel key is present, `latest-<sha1-prefix-of-key>.json`.

Synthetic group prompts and transient metadata are removed. Conversation sanitation preserves
provider-valid tool-use/tool-result sequences. The key-specific latest pointer is what lets a
runtime rebuilt after restart resume the correct channel/thread/sender conversation.

### 11. The bridge publishes progress and final output

During processing, non-final updates go immediately to the outbound bus. The bridge holds the final
text/media until the runtime stream ends, then publishes one final `OutboundMessage` to the same
`channel` and `chat_id` as the inbound message.

Shared-chat/thread metadata is merged into updates so adapters can reply in the proper thread.
Feishu private replies intentionally omit group/thread reply metadata and stay normal direct
messages.

### 12. One dispatcher sends for all channels

`ChannelManager._dispatch_outbound()` consumes the shared outbound queue in FIFO order. It:

1. drops tool hints when `send_tool_hints` is false;
2. drops other progress when `send_progress` is false;
3. looks up the adapter named by `OutboundMessage.channel`; and
4. awaits that adapter's `send()`.

There is one dispatcher, not one per channel. A slow or stuck `send()` can therefore delay outbound
traffic for every enabled channel. Send failures are logged and the message is not retried or
requeued by the manager.

## What is shared across channels

| Shared | Scope and consequence |
| --- | --- |
| ohmo workspace | All channels see the same soul, identity, user profile, personal-memory files, workspace skills/plugins, groups, and attachments root |
| Gateway provider profile | New/refreshed bundles use the profile named in one `gateway.json` |
| Inbound/outbound queues | All adapters feed one bus; ordering is queue arrival order |
| Bridge and runtime pool | One task/key map and one bundle/key map span all channels |
| Core settings and credential stores | Provider auth, permission rules, sandbox, MCP, hooks, and project plugin trust are core-owned |
| Process resources | Task manager and gateway service lifecycle are shared in the process |

Personal-memory files are shared, but an already-cached bundle holds the personal-memory prompt
snapshot from when it was built. A memory change made through one channel is durable immediately but
may not appear in another channel's existing bundle until that bundle refreshes/rebuilds.

## What is isolated across channels

| Isolated | Boundary |
| --- | --- |
| Conversation messages | Normal key includes channel/chat and, for shared chats, thread/sender |
| Runtime engine/client/MCP bundle | One cached `RuntimeBundle` per key |
| Keyed latest snapshot | Hash of exact session key |
| Same-key active task | Bridge task map |
| Reply destination | Each outbound message names one adapter and chat |
| Platform transport state | Owned by each channel SDK adapter |

There is no automatic cross-channel transcript merge, identity federation, broadcast, handoff, or
“continue this Telegram chat in Slack” workflow. Implementing one would require an explicit,
authenticated identity/key mapping and a session migration policy; removing the channel component
from keys would leak history.

## Access-control layers

Remote reachability is the intersection of several controls:

| Layer | Question answered |
| --- | --- |
| Adapter enabled and credentials valid | Is the platform connection active? |
| `allow_from` | Is this sender identity trusted to reach the bus? |
| Adapter mention/group rules | Should this event wake the bot? |
| Feishu bridge group policy | Is this group managed/mentioned/open under ohmo policy? |
| Session-key routing | Which history and active task can the sender affect? |
| Command remote flags/admin opt-in | May this slash command execute remotely? |
| Core permission checker | May the model-selected tool execute? |
| Sensitive-path rules and sandbox | What side effects remain prohibited/isolated? |

An open channel can expose repository tools running in the gateway cwd. Prefer explicit sender IDs;
`["*"]` is an intentional public-access decision. `gateway.json` stores channel tokens/secrets as
plaintext, so restrict filesystem permissions and backup disclosure.

## Media and threading coordination

Where supported, adapters download inbound media under
`<workspace>/attachments/<channel>/` because the service exports `OHMO_WORKSPACE`. The runtime
normalizes paths into image/file context. Platform filenames and download paths must remain bounded
and sanitized by the adapter.

Outbound media is discovered from successful tool results or final image paths, then passed through
`OutboundMessage.media`. Upload, rich rendering, reply IDs, thread roots, encryption, size limits,
and text fallback remain adapter-specific. Use the
[attachments and media reference](ATTACHMENTS_AND_MEDIA.md) before changing those contracts.

## Restart, shutdown, and recovery

SIGTERM/SIGINT or gateway commands set the service stop event. Cleanup:

1. tells the bridge to stop and cancels its tracked tasks;
2. cancels/awaits bridge and channel-manager start tasks;
3. cancels heartbeat/restart-notice tasks;
4. calls every adapter's `stop()` and cancels the outbound dispatcher;
5. writes stopped state and removes the PID file; and
6. on requested restart, replaces the process with `os.execv()`.

Remote restart stores a one-message notice before shutdown. The new process waits, republishes it
through the bus, then removes the notice file. Queue contents and live runtimes are not persisted as
execution objects; only completed/saved snapshots survive.

The runtime pool has no `close_all()` and no inactivity eviction. Cwd changes and command refreshes
close individual bundles, but normal gateway shutdown relies on process exit for remaining clients,
MCP connections, hooks, and sandbox resources.

## Failure and capacity behavior

| Condition | Current behavior |
| --- | --- |
| One adapter fails startup | Error logged/stored on adapter; other adapters can continue |
| Inbound queue grows | No configured bound, spill-to-disk, or load shedding |
| New same-key message | Cancel old task, wait up to three seconds, start replacement |
| Different keys | Run concurrently in separate bundles |
| Slow outbound adapter | Blocks the single dispatcher for other channels |
| Outbound send fails | Log and drop; no manager retry/requeue |
| Gateway restarts | In-memory queues/tasks/bundles lost; saved snapshots restore on later messages |
| Cached sessions grow | No TTL/LRU/maximum bundle count |
| Channel connected but unhealthy | Heartbeat may expose first `last_error`; no per-channel readiness handshake |
| Empty final response | No final outbound message |

These limitations define the current operating envelope. They are tracked as long-running gateway
and concurrency work in the [improvement backlog](../IMPROVEMENTS.md).

## Operator workflow for multiple channels

1. Run `ohmo config --workspace <path>` and enable only the adapters you intend to test.
2. Use explicit `allow_from` identities for every enabled channel.
3. Set the gateway default cwd to the smallest safe tool scope.
4. Start in the foreground with `ohmo gateway run` and verify each adapter independently.
5. Send one private message per platform and confirm separate sessions appear.
6. Test group mentions/policy with non-sensitive prompts before enabling tools broadly.
7. Verify progress/tool-hint flags and thread placement for each adapter.
8. Inspect `<workspace>/logs/gateway.log`, gateway status, and keyed session files after failures.
9. Restart after config/profile changes that require reconstructing channel connections or bundles.
10. Back up the workspace only while the gateway is stopped when a consistent sessions/config/
    memory snapshot matters.

## Source and test map

| Contract | Source | Tests/reference |
| --- | --- | --- |
| Normalized messages and queues | `src/openharness/channels/bus/` | `tests/test_channels/` |
| Sender allowlist/media root | `src/openharness/channels/impl/base.py` | `tests/test_channels/test_base.py` and channel security tests |
| Adapter startup/outbound dispatch | `src/openharness/channels/impl/manager.py` | `tests/test_ohmo/test_gateway.py` |
| Gateway config projection | `ohmo/gateway/config.py`, `ohmo/gateway/models.py` | `tests/test_ohmo/test_cli.py`, `tests/test_ohmo/test_gateway.py` |
| Routing keys | `ohmo/gateway/router.py` | routing cases near the start of `tests/test_ohmo/test_gateway.py` |
| Admission/control/cancellation | `ohmo/gateway/bridge.py` | group-policy, stop/restart, replacement tests in `tests/test_ohmo/test_gateway.py` |
| Per-key runtime/commands/events | `ohmo/gateway/runtime.py` | runtime restore, command security, progress, media, and image-fallback gateway tests |
| Keyed snapshots | `ohmo/session_storage.py` | `tests/test_ohmo/test_ohmo_session_storage.py` |
| Process lifecycle | `ohmo/gateway/service.py` | PID/state/restart tests in `tests/test_ohmo/test_gateway.py` |
| Adapter capabilities | `src/openharness/channels/impl/` | [channel capability matrix](../../reference/CHANNELS.md) |
