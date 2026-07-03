# Prompt handling and the model/tool loop

## Question answered

What happens from the moment a user submits ordinary chat text until OpenHarness produces a final
assistant answer, including multiple model turns and tool-result replay?

For the broader lifecycle including all memory layers, compaction stages, tool governance, and
persistence, see [Prompt, memory, tools, and compaction end to end](PROMPT_MEMORY_TOOLS_COMPACTION_E2E.md).

## End-to-end sequence

```text
UI/headless/ohmo submits text or ConversationMessage
        │
        ▼
handle_line()
  command lookup? ── yes → command handler / optional submitted prompt
        │ no
        ├─ reload settings/hooks as needed
        ├─ rebuild system prompt for latest text
        ▼
QueryEngine.submit_message()
  prepare session memory → sanitize/append user → user_prompt_submit hook
        │
        ▼
run_query(context, messages)
  compact if needed → preprocess images → provider.stream_message(request)
        │
        ├─ text deltas → AssistantTextDelta
        ├─ retry/status → StatusEvent
        └─ completed assistant message → append + AssistantTurnComplete
                 │
                 ├─ no tool uses → stop hook → return
                 └─ tool uses → execute → append user ToolResultBlocks → loop
        │
        ▼
post-turn memory work → save session snapshot → refresh UI state
```

## 1. `handle_line()` separates commands from prompts

The common handler receives a `RuntimeBundle`, submitted text, renderer callbacks, and optionally a
pre-built multimodal `ConversationMessage`. For plain text it checks the built-in/plugin command
registry and then user-invocable skills. A supplied `ConversationMessage` bypasses slash-command
parsing so image content cannot accidentally become a command.

A command can:

- return a local message without a model call;
- request runtime refresh;
- return `submit_prompt`, which is sent through the same engine loop;
- request continuation of pending tool results without adding another user message;
- clear/replay output or terminate the session.

For an ordinary prompt, `handle_line()` reloads effective settings, applies max-turn behavior,
rebuilds the system prompt using the latest text, and calls `engine.submit_message()`.

## 2. QueryEngine owns durable in-process conversation state

`QueryEngine.submit_message()` converts strings to `ConversationMessage`, records a compact user-goal
summary in tool metadata, prepares file-backed session-memory metadata, sanitizes existing messages,
and appends the new user message. It fires `user_prompt_submit` hooks before creating `QueryContext`.

`QueryContext` is the immutable-per-run dependency set for the lower loop: client, registry,
permission checker, cwd, model, prompt, token limits, callbacks, hooks, and mutable tool carry-over
metadata. The engine passes a list copy into `run_query()` and updates its owned message history when
assistant turns complete.

Coordinator mode may append a synthetic user-context message for the request. The query loop removes
and repositions that context around assistant/tool messages so provider ordering remains valid.

## 3. Each model turn receives the complete callable contract

At the beginning of each loop turn, `run_query()`:

1. Checks proactive auto-compaction; it may microcompact tool results or summarize older messages.
2. Converts image blocks to text when the selected model lacks vision support.
3. Calls `api_client.stream_message()` with an `ApiMessageRequest` containing:
   - model;
   - current messages;
   - current system prompt;
   - bounded completion-token limit;
   - every tool schema from `ToolRegistry.to_api_schema()`;
   - reasoning effort.

Provider clients translate this normalized request to their wire format. Streaming text becomes
`AssistantTextDelta`; provider retries become `StatusEvent`; completion yields a normalized assistant
`ConversationMessage` and usage.

The assistant message is appended before any tool execution. This ordering is required because the
next provider request must include the assistant's tool-use block followed by matching user
tool-result blocks.

## 4. Tool requests create additional model turns

If the completed assistant message contains no tool-use blocks, the loop fires the `stop` hook and
returns. Otherwise:

- one tool call executes sequentially so its events stream immediately;
- multiple tool calls execute concurrently through `asyncio.gather(return_exceptions=True)`;
- every requested tool ID receives a `ToolResultBlock`, including unknown tools, invalid arguments,
  denials, and raised exceptions;
- tool-result blocks are appended together as a user-role message;
- the `while` loop calls the provider again with the expanded conversation.

Guaranteeing one result per tool-use ID prevents provider rejection of an incomplete tool-call turn.
The loop stops when the model returns no tools or raises `MaxTurnsExceeded` after the configured cap.

## 5. Errors are made recoverable where possible

- Provider completion-token errors can reduce the output-token cap and retry the same turn.
- Context-length errors trigger one forced reactive compaction attempt before surfacing an error.
- Network-like failures become actionable `ErrorEvent` messages.
- Empty assistant messages are dropped rather than poisoning persisted history.
- Tool exceptions become error results so the model can diagnose or choose another approach.
- Oversized tool output is offloaded to an artifact and replaced with bounded inline content.

## 6. Post-turn work and persistence

In `QueryEngine.submit_message()`'s `finally` block, OpenHarness updates file-backed session memory,
optionally extracts durable memory, and schedules optional auto-dream consolidation. Back in
`handle_line()`, the configured `SessionBackend` saves messages, usage, system prompt, session ID,
and selected JSON-safe tool metadata. This happens for successful turns and max-turn exits.

Memory selection happens while building the system prompt before submission; memory persistence and
extraction happen after the query run. See [Memory, sessions, and compaction](MEMORY_SESSION_COMPACTION.md).

## Stream events and consumers

| Event | Meaning | Typical consumers |
| --- | --- | --- |
| `AssistantTextDelta` | Incremental assistant text | print renderer, React backend, `ohmo` reply accumulator |
| `AssistantTurnComplete` | Normalized assistant message and usage | transcript, engine history, tests |
| `ToolExecutionStarted` | Tool name and input accepted for execution | UI status and `ohmo` tool hints |
| `ToolExecutionCompleted` | Normalized output/error/metadata | transcript, media handling, continuation |
| `CompactProgressEvent` | Compaction phase/status | terminal and gateway progress |
| `StatusEvent` | Retry, token clamp, or operational status | all renderers |
| `ErrorEvent` | Request-level failure | user-facing error paths |

## Where to change behavior

| Change | Primary owner | Cross-flow checks |
| --- | --- | --- |
| Conversation/message shape | `src/openharness/engine/messages.py` | every provider, persistence, compaction, UI, `ohmo` |
| Turn ordering/replay | `src/openharness/engine/query.py` | tools, providers, max turns, session resume |
| Per-session state/usage | `src/openharness/engine/query_engine.py` | persistence and memory hooks |
| Command versus prompt behavior | `src/openharness/ui/runtime.py`, command registry | local UI and remote `ohmo` commands |
| Provider translation | selected client under `src/openharness/api/` | text, tools, reasoning, usage, errors |

## Verification map

- `tests/test_engine/test_query_engine.py`: text, tools, parallel calls, retries, compaction, limits.
- `tests/test_engine/test_messages.py`: serialization/sanitization contracts.
- `tests/test_tools/test_integration_flows.py`: registry-level tool workflows.
- `tests/test_ui/test_react_backend.py`: stream-to-protocol behavior.
- `tests/test_ohmo/test_gateway.py`: stream-to-channel behavior and snapshots.
- `tests/test_api/`: provider request and replay conversion.
