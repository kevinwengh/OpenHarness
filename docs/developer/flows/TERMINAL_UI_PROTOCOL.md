# React terminal and Python backend protocol

## Question answered

How does the TypeScript Ink terminal communicate with the Python runtime, and why does an ordinary
interactive `oh` session involve a frontend process and a backend process?

## Process topology

```text
shell runs generated `oh` launcher
        │
        ▼
Python cli.main() → run_repl() → launch_react_tui()
        │
        ├─ OPENHARNESS_FRONTEND_CONFIG contains backend argv + initial state
        ▼
tsx frontend/terminal/src/index.tsx
        │ spawns backend argv
        ▼
python -m openharness --backend-only ...
        │
        ▼
run_backend_host() / ReactBackendHost
        ├─ stdin: JSON FrontendRequest lines
        └─ stdout: JSON BackendEvent lines
```

## 1. Frontend location and launch

`get_frontend_dir()` first checks `openharness/_frontend` inside an installed wheel, then the
repository's `frontend/terminal`. `pyproject.toml` force-includes the terminal package metadata,
TypeScript config, and source in the Python wheel.

`launch_react_tui()` ensures Node dependencies exist, builds the backend command, serializes it into
`OPENHARNESS_FRONTEND_CONFIG`, and starts `tsx src/index.tsx` with terminal stdio inherited. The
backend command uses the same interpreter and begins:

```text
python -m openharness --backend-only --cwd ...
```

Model, effort, URL, API format, permission mode, and other explicit launch overrides are forwarded
as arguments. The API key can also be forwarded, so diagnostics and process logging must never print
the full command unredacted.

## 2. Protocol models

`src/openharness/ui/protocol.py` is the Python schema authority. `FrontendRequest` accepts request
types such as:

- `submit_line` with text and optional image attachments;
- `permission_response` and `question_response` correlated by request ID;
- selection/list requests;
- `interrupt` and `shutdown`.

`BackendEvent` emits types such as:

- `ready`, state/task/status snapshots;
- transcript items and assistant deltas/completion;
- tool started/completed;
- compact progress;
- modal and selection requests;
- todo, plan-mode, and swarm status;
- error and shutdown.

`frontend/terminal/src/types.ts` mirrors these shapes. Any field/type change is a two-language
contract change, even if Python and TypeScript each compile independently.

## 3. Backend lifecycle

`run_backend_host()` optionally changes to the requested cwd, builds `BackendHostConfig`, constructs
`ReactBackendHost`, and calls `run()`. The host builds/starts a normal `RuntimeBundle`, emits initial
state, then reads newline-delimited JSON requests.

Submitted lines are processed as active async requests so an `interrupt` can cancel the current
turn. Permission and question responses resolve pending futures rather than entering the normal line
queue. Concurrent permission prompts are serialized to prevent one modal replacing another.

The host converts engine `StreamEvent` objects into protocol `BackendEvent` objects. It also emits
transcript rows and a final `line_complete` marker; the frontend uses that marker, rather than an
assistant text event alone, to end the busy state after tool calls.

## 4. Images and multimodal input

The frontend validates image MIME type and base64 data. `_build_user_message_with_images()` creates
a `ConversationMessage` containing one text block plus image blocks and passes that object to
`handle_line()`. Because `user_message` is supplied, slash-command parsing is bypassed. The query
loop/provider then either sends images natively or preprocesses them for a non-vision model.

## 5. Output ownership

The Python backend owns runtime truth: resolved settings, tasks, MCP/bridge status, transcript events,
and permission decisions. The React frontend owns presentation and local interaction state. It must
not infer that an action succeeded merely because it sent a request; it waits for backend events.

Print mode does not use this protocol. It calls the same runtime/handler directly with simple
render callbacks. The Textual UI is another consumer of runtime events and should be checked when
event meaning changes, even though it does not use the React JSON process boundary.

## 6. Shutdown and failure behavior

- Malformed frontend payloads become protocol errors rather than arbitrary calls.
- Interrupt cancels active work and leaves the host able to accept another line.
- Backend shutdown closes runtime-owned MCP, sandbox, hook, and API resources.
- The launcher propagates the frontend process exit code.
- Terminal cleanup restores cursor/newline state so the shell prompt remains usable.

## Where to change behavior

| Concern | Python side | TypeScript side |
| --- | --- | --- |
| Request/event schema | `src/openharness/ui/protocol.py` | `frontend/terminal/src/types.ts` |
| Stream conversion and dialogs | `src/openharness/ui/backend_host.py` | `frontend/terminal/src/App.tsx` |
| Process launch/packaging | `src/openharness/ui/react_launcher.py`, `pyproject.toml` | `frontend/terminal/src/index.tsx`, package config |
| Transcript rendering | emitted protocol events | Ink components in `App.tsx` |

## Verification map

- `tests/test_ui/test_react_backend.py`: protocol, cancellation, dialogs, images, events.
- `tests/test_ui/test_react_launcher.py`: process command and runtime selection.
- `tests/test_ui/test_tui_exit_sequence.py`: terminal cleanup.
- `tests/test_ui/test_modes.py`: mode/state propagation.
- `frontend/terminal`: `npx tsc --noEmit` for mirrored types.
- `scripts/react_tui_e2e.py` and `scripts/test_tui_interactions.py`: opt-in interaction checks.
