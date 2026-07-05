# Local OpenHarness web UI

The `oh web` command starts a clean browser workspace for the reusable OpenHarness runtime. It is a
local interface in the same Python process, not a hosted service and not an `ohmo` gateway console.

## Start it

```bash
oh web
```

The command binds an available port on `127.0.0.1`, prints a launch URL, and opens the default
browser. To copy the URL yourself or use a predictable local port:

```bash
oh web --no-open --port 8765
```

Use `--cwd /path/to/project` to select a different workspace. Non-loopback `--host` values are
rejected in the initial release.

## Current behavior

The current implementation provides:

- a runtime overview showing the active profile, provider, model, authentication state, permission
  mode, sandbox state, effort, and turn limit;
- global `Cmd/Ctrl+K` search across navigation, bounded session summaries, slash commands, and
  installed capabilities; choosing a command prepares it in the Workbench instead of executing it;
- responsive desktop, tablet, and mobile navigation for Overview, Workbench, Sessions, Runtime,
  Capabilities, Work, Knowledge, and Autopilot;
- light and dark themes, a keyboard-accessible navigation drawer, explicit loading/error/retry
  states, visible focus, reduced-motion handling, and mobile safe-area behavior;
- a streaming Workbench with text and image input, interrupt, tool timelines, runtime progress,
  permission and edit decisions, agent questions, and reconnect feedback;
- a recent Sessions list with bounded summaries, timestamps, model, message count, direct resume,
  selector fallback, refresh, and an explicit new-runtime action;
- Runtime controls for provider profile, model, permission mode, effort, turn limit, fast mode,
  reasoning passes, and output style through the same command owners used by the terminal;
- a searchable Capabilities inventory for tools, commands, skills, plugins, hooks, MCP connections,
  provider status, and the project-plugin trust boundary;
- Work views for tasks, bridge sessions, cron schedules, and bounded run history, with confirmed
  stop, enable/disable, and run-now actions;
- searchable Knowledge previews with disabled-memory filtering and no raw local paths; and
- Autopilot registry statistics, queued cards, recent journal entries, and manual idea intake.

All eight main navigation areas are operational. Less common configuration and destructive
operations remain intentionally CLI/Workbench-first instead of being exposed through a generic web
dispatcher. See the [web UI specification](../architecture/WEB_UI_SPEC.md) for support depth and
review gates.

Images are limited to four per turn, 2 MB each, and 6 MB total before base64 encoding. Completed
assistant messages and plan checklists render GitHub-flavored Markdown without raw HTML. Links are
limited to relative, HTTP(S), and email targets; unsafe protocols become plain text, and
model-authored remote images become inert text instead of network requests. Streaming text remains
plain until the completed message arrives so partially received Markdown cannot destabilize layout.

The Stage 3 resource surface exposes launch-token-protected, bounded snapshots for Capabilities,
Work, Knowledge, and Autopilot. It provides only these state-changing actions:
stop a task, stop a bridge, enable or disable a cron job, run a cron job now, and enqueue a manual
Autopilot idea. Every action has a strict request model and delegates to the existing subsystem
owner; there is no generic command, Python, tool, or plugin dispatch endpoint. Immediate cron runs
and stop/toggle actions require a consequence-specific browser confirmation. Manual Autopilot
intake queues a card but does not start an agent run. Work and Autopilot mutations are temporarily
disabled while the shared Workbench runtime is processing an active turn.

## Local security boundary

Each launch creates a high-entropy token. It appears in the URL fragment, which browsers do not send
as part of the HTTP request. The frontend consumes the fragment, removes it from browser history,
keeps it only for that tab session, and sends it in the `Authorization` header for data requests.

The host also:

- validates the loopback bind and the request host;
- rejects missing tokens and cross-origin API access;
- applies a restrictive Content Security Policy and framing, referrer, MIME, permissions, and cache
  headers;
- serves no third-party scripts, fonts, telemetry, or images;
- returns a typed bootstrap snapshot rather than serializing settings, credential files, environment
  values, API keys, tokens, or provider endpoint URLs.
- requires an exact same-origin header for state-changing requests and rejects action names or
  fields outside the explicit allowlist;
- bounds resource lists and presentation strings, omits command/prompt/output bodies from Work,
  and does not import disabled project-plugin Python when Capabilities is inspected.
- exposes only bounded session ID, summary, model, message count, and timestamp fields to global
  search and the Sessions screen; malformed resume identifiers are omitted.

Static bundle files are public on the loopback port, but every `/api/` request requires the launch
token. Treat the launch URL as a short-lived local secret and stop the process with Ctrl+C when the
workspace is no longer needed.

One browser tab controls the runtime. A refresh or brief connection loss can reclaim the controller
for five seconds. During that window, at most 256 presentation events are retained. If the tab does
not return, pending approvals are denied, pending questions are cancelled, the active turn is
interrupted, and runtime resources are closed. A concurrent tab receives an explicit
already-controlled error.

## Build and validate from source

Use Node 20:

```bash
cd frontend/web
npm ci
npm test
npm run build
npm audit

cd ../..
uv run pytest -q tests/test_ui/test_web_server.py tests/test_ui/test_web_resources.py
```

The production build is written to `src/openharness/_web` and included in the Python wheel. CI
rebuilds those assets and fails if checked-in package assets no longer match the React source.
