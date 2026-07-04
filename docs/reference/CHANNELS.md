# Channel adapters and capability matrix

OpenHarness normalizes channel SDK events into `InboundMessage` and `OutboundMessage` on an
in-memory `MessageBus`. `ChannelManager` creates enabled adapters and dispatches outbound messages;
ohmo adds authorization, session-key routing, cancellation, runtime pooling, and final/progress
translation.

## Common contract

`channels/impl/base.py::BaseChannel` defines `start()`, `stop()`, `send()`, `is_allowed()`, and the
inbound publish helper. `ChannelManager.start_all()` starts configured adapters and one outbound
dispatcher; `stop_all()` cancels and awaits owned tasks. Empty `allow_from` is deny-by-default and
`["*"]` is an explicit wildcard for adapters using the base policy.

Channel access control only decides who can reach the runtime. Model tool permissions separately
decide what the reached runtime may do.

## Configuration and support surface

| Adapter | Config model | Guided by `ohmo config` | Transport / notable behavior |
| --- | --- | --- | --- |
| Telegram | `TelegramConfig` | yes | bot polling/API; reply-to option; sender allowlist |
| Slack | `SlackConfig` | yes | Socket Mode tokens; adapter-specific DM/group policy caveats |
| Discord | `DiscordConfig` | yes | gateway WebSocket/intents; sender/group mention policy |
| Feishu/Lark | `FeishuConfig` | yes | SDK WebSocket thread; managed groups, mentions, rich/media replies |
| DingTalk | `DingTalkConfig` | manual | stream/robot credentials and outbound API |
| Email | `EmailConfig` | manual | IMAP-style polling plus SMTP; attachments |
| QQ | `QQConfig` | manual | app/token credentials and bot events |
| Matrix | `MatrixConfig` | manual | sync loop; rooms, mentions, threads, encrypted media support where dependencies allow |
| WhatsApp | `WhatsAppConfig` | manual | configured bridge WebSocket |
| Mochat | `MochatConfig` | manual | socket/poll fallback workers and target serialization |

“Manual” means the schema and manager contain an adapter but the current guided ohmo wizard does not
collect all required fields. It is not a production-support promise. Inspect the adapter and its
tests before deployment.

## Routing and conversation isolation

`ohmo/gateway/router.py::session_key_for_message()` derives a key from channel/account/chat/thread
and, for shared conversations, sender identity. Adapter metadata such as `thread_id`, root event ID,
or chat type affects isolation. Changing metadata or key construction can merge private histories or
split continuity and requires migration analysis.

`OhmoGatewayBridge` keeps one active processing task per key and cancels the older task when a new
same-key message arrives. `OhmoSessionRuntimePool` does not add its own same-key lock; it relies on
the bridge invariant.

## Authority matrix

| Control | Layer | Purpose |
| --- | --- | --- |
| `enabled` and valid credentials | adapter construction | whether a platform is connected |
| `allow_from` | base/adapter ingress | allowed sender identities |
| group/mention policy | adapter ingress | when a shared room wakes the bot |
| managed-group registry | ohmo/Feishu policy | application-created group behavior |
| `remote_invocable` | slash command | whether a command may run remotely |
| remote admin allowlist | ohmo gateway config | explicit exception for selected admin commands |
| permission mode/rules | engine tool path | allowed model-selected side effects |

Never substitute mention-only behavior for sender authorization. The current Slack schema/wizard and
adapter have known access-control mismatches documented in the ohmo user guide; use a private test
workspace until they are resolved.

## Media and thread behavior

Capabilities vary by SDK and adapter. Inbound media is downloaded into a bounded local media root
where implemented, converted into normalized media paths, and later loaded into model image/file
handling. Outbound `media` paths can be uploaded by supporting adapters; failures may fall back to
text markers or error updates.

Path construction must sanitize platform filenames and remain inside the configured media root.
Size limits, encrypted media, reply threading, mentions, and rich Markdown/card rendering are
adapter-specific. Use `tests/test_channels` and `tests/test_ohmo` as the executable contract.

## Adding or changing an adapter

1. Implement `BaseChannel` in `channels/impl`.
2. Add a typed config model in `config/schema.py`.
3. Register it in `ChannelManager._init_channels()`.
4. Preserve allowlist, group/mention, thread, media, reconnect, rate-limit, and cleanup behavior.
5. Ensure all SDK callbacks cross into the owning asyncio loop safely.
6. Add deterministic security and lifecycle tests; keep live SDK tests opt-in.
7. Check `channels/UPSTREAM` before broad refactoring.

See [Extending OpenHarness](../EXTENDING.md#add-a-channel) and the
[ohmo routing guide](../developer/ohmo/ROUTING_BRIDGE_AND_CONCURRENCY.md).
