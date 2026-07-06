# Web UI rendered evidence

These are the 31 reviewed screenshots from the July 5, 2026 CLI Playwright completion audit. They
were captured from commit `61f7d0d` with the deterministic, credential-free fixture documented in
the [Playwright audit](../../WEB_UI_PLAYWRIGHT_AUDIT.md). The corresponding run passed all route,
dialog, browser-error, and horizontal-overflow assertions.

The images are completion evidence, not pixel-perfect golden snapshots. Platform font rendering
may vary, so future updates should rerun the browser assertions, inspect every replacement, and
commit refreshed images only when the documented UI intentionally changes.

## Desktop — 1440×900

### Main areas

| Overview | Workbench | Sessions |
| --- | --- | --- |
| [![Desktop overview](desktop/overview.png)](desktop/overview.png) | [![Desktop Workbench](desktop/workbench.png)](desktop/workbench.png) | [![Desktop Sessions](desktop/sessions.png)](desktop/sessions.png) |

| Runtime | Capabilities | Work |
| --- | --- | --- |
| [![Desktop Runtime](desktop/runtime.png)](desktop/runtime.png) | [![Desktop Capabilities](desktop/capabilities.png)](desktop/capabilities.png) | [![Desktop Work](desktop/work.png)](desktop/work.png) |

| Knowledge | Autopilot |
| --- | --- |
| [![Desktop Knowledge](desktop/knowledge.png)](desktop/knowledge.png) | [![Desktop Autopilot](desktop/autopilot.png)](desktop/autopilot.png) |

### Interaction states

| Command palette | Runtime chooser | Permission review |
| --- | --- | --- |
| [![Desktop command palette](desktop/command-palette.png)](desktop/command-palette.png) | [![Desktop runtime chooser](desktop/runtime-chooser.png)](desktop/runtime-chooser.png) | [![Desktop permission review](desktop/permission-review.png)](desktop/permission-review.png) |

| Resource detail | Light theme |
| --- | --- |
| [![Desktop resource detail](desktop/resource-detail.png)](desktop/resource-detail.png) | [![Desktop light-theme Workbench](desktop/workbench-light.png)](desktop/workbench-light.png) |

## Tablet — 1024×768

| Overview | Workbench | Sessions |
| --- | --- | --- |
| [![Tablet overview](tablet/overview.png)](tablet/overview.png) | [![Tablet Workbench](tablet/workbench.png)](tablet/workbench.png) | [![Tablet Sessions](tablet/sessions.png)](tablet/sessions.png) |

| Runtime | Capabilities | Work |
| --- | --- | --- |
| [![Tablet Runtime](tablet/runtime.png)](tablet/runtime.png) | [![Tablet Capabilities](tablet/capabilities.png)](tablet/capabilities.png) | [![Tablet Work](tablet/work.png)](tablet/work.png) |

| Knowledge | Autopilot | Resource detail |
| --- | --- | --- |
| [![Tablet Knowledge](tablet/knowledge.png)](tablet/knowledge.png) | [![Tablet Autopilot](tablet/autopilot.png)](tablet/autopilot.png) | [![Tablet resource detail](tablet/resource-detail.png)](tablet/resource-detail.png) |

## Mobile — 390×844

| Overview | Workbench | Sessions |
| --- | --- | --- |
| [![Mobile overview](mobile/overview.png)](mobile/overview.png) | [![Mobile Workbench](mobile/workbench.png)](mobile/workbench.png) | [![Mobile Sessions](mobile/sessions.png)](mobile/sessions.png) |

| Runtime | Capabilities | Work |
| --- | --- | --- |
| [![Mobile Runtime](mobile/runtime.png)](mobile/runtime.png) | [![Mobile Capabilities](mobile/capabilities.png)](mobile/capabilities.png) | [![Mobile Work](mobile/work.png)](mobile/work.png) |

| Knowledge | Autopilot | Resource detail sheet |
| --- | --- | --- |
| [![Mobile Knowledge](mobile/knowledge.png)](mobile/knowledge.png) | [![Mobile Autopilot](mobile/autopilot.png)](mobile/autopilot.png) | [![Mobile resource detail sheet](mobile/resource-detail.png)](mobile/resource-detail.png) |

## Refresh procedure

Run this from `frontend/web` after installing Playwright Chromium:

```bash
WEB_AUDIT_OUTPUT=../../docs/testing/images/web-ui-playwright npm run test:e2e
```

Review all 31 files before staging them. The default `npm run test:e2e` path remains under `/tmp`
so routine local and CI runs do not rewrite documentation evidence.
