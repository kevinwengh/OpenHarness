# Local web UI Playwright audit

This is the reproducible rendered-browser gate for the local `oh web` interface. It runs entirely
from the CLI, does not use Codex Desktop, and does not make model calls or read a contributor's
OpenHarness configuration.

## What the gate exercises

Playwright opens the packaged production assets through the real loopback-only `WebUiServer`, uses
the normal launch-fragment token exchange, authenticates the real WebSocket endpoint, and consumes
the shared `FrontendRequest` / `BackendEvent` protocol. A deterministic Python fixture replaces
only environment-dependent owners:

- model execution emits stable transcript, tool, todo, streaming, selection, and permission events;
- resource adapters return bounded sessions, capabilities, work, knowledge, and Autopilot data;
- allowlisted actions return inert success results and never mutate repository or user state.

The fixture lives at `scripts/run_web_visual_fixture.py`. It is test infrastructure, not another
runtime implementation or a user-facing server command.

The browser suite covers:

- Overview, Workbench, Sessions, Runtime, Capabilities, Work, Knowledge, and Autopilot;
- 1440×900 desktop, 1024×768 tablet, and 390×844 mobile viewports;
- desktop command-palette search, runtime choice, permission denial, and light-theme paint;
- responsive capability details, including the mobile bottom sheet;
- absence of uncaught page errors, console errors, and page-level horizontal overflow.

The suite is serialized because the production host intentionally allows one controlling browser
socket. Parallelizing projects against one fixture would test a prohibited multi-tab state rather
than responsive behavior.

## Run it from the CLI

From a clean checkout, install dependencies and the pinned browser once:

```bash
uv sync --extra dev
cd frontend/web
npm ci
npx playwright install chromium
```

Run the rendered gate:

```bash
npm run test:e2e
```

The script rebuilds `src/openharness/_web` before starting Playwright. On Linux CI,
`npx playwright install --with-deps chromium` also installs required system libraries.

Successful runs write fixed-viewport screenshots under
`/tmp/openharness-web-audit/screenshots/<project>/`. Override that location when useful:

```bash
WEB_AUDIT_OUTPUT=/tmp/my-web-audit npm run test:e2e
```

Routine screenshots are review evidence, not golden pixel snapshots, so the default output stays
outside the repository to avoid platform/font churn. The 31 manually reviewed completion frames
are preserved in the [rendered evidence gallery](images/web-ui-playwright/README.md). Playwright
retains a failure screenshot and trace under `frontend/web/test-results/`; that directory is
ignored by Git.

## Current audit result

The July 5, 2026 completion run passed seven checks with two deliberate skips: the interaction
scenario runs once on desktop, while route and detail coverage run in all three projects. The run
produced 31 viewport screenshots, including all main areas, responsive details, the command
palette, runtime chooser, permission review, and a light-theme Workbench. Those exact reviewed
frames are versioned in the [documentation gallery](images/web-ui-playwright/README.md).

Rendered review found one product defect: at the tablet breakpoint, CSS made the rail icon-only
without preserving the buttons' accessible names. Every navigation button now carries its stable
area label, and the tablet Playwright path locates and operates those controls by role and name.

This gate proves deterministic rendering and local transport integration. It does not prove a real
provider endpoint, native browser differences beyond Chromium, OS font identity, or model-quality
behavior. Use `harness-eval` only when a real API/model validation is explicitly required.
