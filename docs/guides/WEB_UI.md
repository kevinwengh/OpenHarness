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

## Current Stage 1 behavior

The first implementation increment provides:

- a runtime overview showing the active profile, provider, model, authentication state, permission
  mode, sandbox state, effort, and turn limit;
- responsive desktop, tablet, and mobile navigation for Overview, Workbench, Sessions, Runtime,
  Capabilities, Work, Knowledge, and Autopilot;
- light and dark themes, a keyboard-accessible navigation drawer, explicit loading/error/retry
  states, visible focus, reduced-motion handling, and mobile safe-area behavior;
- direct deep links to each area, with honest staged placeholders where an operational screen has
  not been connected yet.

The Overview is operational now. The other routes establish the stable information architecture but
do not yet start conversations or mutate configuration. Those capabilities are delivered through
the workbench and operational-area stages described in the
[web UI specification](../architecture/WEB_UI_SPEC.md).

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

Static bundle files are public on the loopback port, but every `/api/` request requires the launch
token. Treat the launch URL as a short-lived local secret and stop the process with Ctrl+C when the
workspace is no longer needed.

## Build and validate from source

Use Node 20:

```bash
cd frontend/web
npm ci
npm test
npm run build

cd ../..
uv run pytest -q tests/test_ui/test_web_server.py
```

The production build is written to `src/openharness/_web` and included in the Python wheel. CI
rebuilds those assets and fails if checked-in package assets no longer match the React source.
