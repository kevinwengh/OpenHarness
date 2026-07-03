# Local LM Studio manual test flow

This runbook validates a source checkout against an LM Studio model exposed through the
Anthropic-compatible Messages API. It covers four distinct boundaries:

1. LM Studio itself;
2. the headless `oh` runtime;
3. the React/Ink terminal frontend and Python backend;
4. the `ohmo` local CLI, personal workspace, and shared terminal frontend.

Run the checks in order. A later check assumes the earlier provider and server checks passed.
Unless a step says otherwise, run commands from the OpenHarness repository root.

This is a live manual test: model output is nondeterministic, and the live steps require a locally
running model. The normal unit test suite remains offline.

The happy-path sequence is:

```text
start LM Studio
  -> curl /v1/messages
  -> uv run oh provider add ...
  -> uv run oh setup lmstudio-anthropic
  -> uv run oh --dry-run ...
  -> uv run oh -p ...
  -> uv run oh                 (React terminal + OpenHarness backend)
  -> uv run ohmo init/config
  -> uv run ohmo doctor
  -> uv run ohmo -p ...
  -> uv run ohmo               (same React terminal + ohmo backend)
```

## What each phase proves

| Phase | Boundary under test | Does not prove |
| --- | --- | --- |
| Direct `curl` | LM Studio server, token, model ID, Anthropic endpoint | OpenHarness configuration |
| `oh --dry-run` | Profile selection, auth resolution, prompt/tool discovery | Network connectivity or model behavior |
| `oh -p` | Provider client, streaming, prompt loop, optional tool replay | React terminal rendering |
| Interactive `oh` | Python launcher, TypeScript frontend, backend protocol, permissions | `ohmo` workspace specialization |
| `ohmo -p` | ohmo prompt, memory, session backend, shared runtime | Interactive frontend behavior |
| Interactive `ohmo` | Shared terminal frontend with the ohmo backend | Remote channel delivery |

Passing a text-only prompt does not establish tool calling, parallel tool calls, image support,
reasoning-field compatibility, or the model's usable context length. Test each capability that a
change claims to support.

## 1. Prepare the checkout and scratch state

Install the Python development environment:

```bash
uv sync --extra dev
```

Use Node.js 20 for terminal checks, matching the repository CI environment:

```bash
node --version
```

The expected major version is `v20`.

Define the model ID and a scratch root. Replace the example model with the exact API identifier
shown by LM Studio.

```bash
export LMSTUDIO_MODEL="ibm/granite-4-micro"
export MANUAL_ROOT="${TMPDIR:-/tmp}/openharness-lmstudio-manual"
export MANUAL_PROJECT="$MANUAL_ROOT/project"

export OPENHARNESS_CONFIG_DIR="$MANUAL_ROOT/openharness-config"
export OPENHARNESS_DATA_DIR="$MANUAL_ROOT/openharness-data"
export OPENHARNESS_LOGS_DIR="$MANUAL_ROOT/openharness-logs"
export OHMO_WORKSPACE="$MANUAL_ROOT/.ohmo"

mkdir -p "$MANUAL_PROJECT"
printf '# Manual test project\n\nmarker: LOCAL_FILE_OK\n' > "$MANUAL_PROJECT/README.md"
```

These variables isolate settings, sessions, logs, and the ohmo workspace from normal user state.
Credential storage is separate: `--api-key` uses the operating-system keyring when one is usable,
otherwise it writes `$OPENHARNESS_CONFIG_DIR/credentials.json` with mode `0600`.

Use an LM Studio API token when **Require Authentication** is enabled:

```bash
export LM_API_TOKEN="your-lm-studio-token"
```

When authentication is disabled, use a non-secret placeholder:

```bash
export LM_API_TOKEN="lmstudio"
```

Never paste a real token into a checked-in file or test transcript.

## 2. Start and isolate LM Studio

Load the selected model, then start LM Studio's server from its Developer tab or in another
terminal:

```bash
lms server start --port 1234
```

Verify the Anthropic-compatible endpoint without OpenHarness:

```bash
curl http://localhost:1234/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: $LM_API_TOKEN" \
  -d "{
    \"model\": \"$LMSTUDIO_MODEL\",
    \"max_tokens\": 64,
    \"messages\": [
      {\"role\": \"user\", \"content\": \"Reply with exactly LMSTUDIO_SERVER_OK\"}
    ]
  }"
```

Pass criteria:

- the request reaches `POST /v1/messages`;
- the response contains an assistant content block;
- no `401`, `404`, connection, or model-not-found error occurs.

Stop here if this fails. OpenHarness cannot correct an LM Studio server, token, endpoint, or model
identifier problem.

## 3. Create and activate the OpenHarness profile

Create a profile scoped to this local endpoint:

```bash
uv run oh provider add lmstudio-anthropic \
  --label "LM Studio (Anthropic)" \
  --provider anthropic \
  --api-format anthropic \
  --auth-source anthropic_api_key \
  --model "$LMSTUDIO_MODEL" \
  --base-url http://localhost:1234 \
  --api-key "$LM_API_TOKEN"
```

The command writes the non-secret profile to
`$OPENHARNESS_CONFIG_DIR/settings.json`. The token goes to the system keyring or the fallback
credentials file; it is not stored as part of the profile JSON.

Run setup against the named profile:

```bash
uv run oh setup lmstudio-anthropic
```

For a newly created profile, setup asks whether to replace the existing key. Answer **No** unless
you intentionally want to enter a different token. Because `provider add` records one allowed
model, setup keeps that model and activates the profile.

Running `uv run oh setup` without the profile argument is also valid: select
**LM Studio (Anthropic)** from the workflow menu.

Confirm the result:

```bash
uv run oh provider list
```

Pass criteria:

```text
* lmstudio-anthropic: LM Studio (Anthropic) [ready]
    auth=anthropic_api_key model=<your model> base_url=http://localhost:1234
```

The leading `*` means the profile is active. `[ready]` means OpenHarness resolved a credential; it
does not mean a live model request succeeded.

## 4. Inspect configuration without a model call

Run the safe preview:

```bash
uv run oh \
  --cwd "$MANUAL_PROJECT" \
  --dry-run \
  --output-format json \
  -p "Check the local provider"
```

Verify these fields near the beginning of the JSON output:

```json
{
  "settings": {
    "active_profile": "lmstudio-anthropic",
    "provider": "anthropic",
    "api_format": "anthropic",
    "model": "YOUR_MODEL_ID",
    "base_url": "http://localhost:1234"
  },
  "validation": {
    "auth_status": "configured"
  },
  "readiness": {
    "level": "ready"
  }
}
```

Dry-run also lists the commands, skills, tools, plugins, and MCP configuration that would be given
to the runtime. It does not connect to LM Studio or start MCP servers.

## 5. Test headless `oh`

Start with a text-only streaming request:

```bash
uv run oh \
  --cwd "$MANUAL_PROJECT" \
  --max-turns 4 \
  -p "Reply with exactly OH_TEXT_OK"
```

Pass criteria:

- streamed assistant text appears;
- the process exits successfully;
- LM Studio logs one Anthropic Messages request;
- no provider conversion or malformed-stream error appears.

Next test a read-only tool round trip:

```bash
uv run oh \
  --cwd "$MANUAL_PROJECT" \
  --max-turns 6 \
  -p "Use read_file to read README.md, then reply with the marker value and nothing else."
```

Expected final content:

```text
LOCAL_FILE_OK
```

This second check should produce at least two provider requests: the assistant tool request, then a
request containing the matching tool result. If the text-only check passes but this fails, inspect
the selected model's tool-use support and LM Studio prompt template before changing OpenHarness.

## 6. Test the OpenHarness terminal application

The supported terminal path starts with Python, not `npm start`:

```text
uv run oh
  -> launch_react_tui()
  -> tsx frontend/terminal/src/index.tsx
  -> python -m openharness --backend-only
```

First validate the TypeScript source:

```bash
cd frontend/terminal
npm ci
npx tsc --noEmit
cd ../..
```

Then launch the complete frontend/backend process pair:

```bash
uv run oh --cwd "$MANUAL_PROJECT"
```

Perform these interactions:

1. Confirm the welcome/status area shows the expected model.
2. Enter `/status` and verify the session uses the LM Studio profile/model.
3. Submit:

   ```text
   Use write_file to create terminal-smoke.txt with exact content TERMINAL_TOOL_OK, then read it back and report the content.
   ```

4. In default permission mode, verify a write/diff approval appears. Approve it once.
5. Confirm tool-start/tool-complete rendering appears and the final answer contains
   `TERMINAL_TOOL_OK`.
6. Enter `/exit`, or press `Ctrl+C` while idle, and confirm the shell cursor and prompt are restored.

Verify the filesystem result outside the TUI:

```bash
test "$(cat "$MANUAL_PROJECT/terminal-smoke.txt")" = "TERMINAL_TOOL_OK"
```

Running `npm start` directly is a frontend-development primitive, not the normal integration path.
It requires `OPENHARNESS_FRONTEND_CONFIG` containing a backend command. Use `uv run oh` for the
representative end-to-end terminal test because the Python launcher constructs that configuration
and forwards the active runtime options.

## 7. Initialize and configure ohmo

The ohmo workspace is distinct from OpenHarness settings and project memory, but it reuses the
OpenHarness provider profiles and credential resolution configured above.

Initialize a scratch personal workspace without entering the channel wizard immediately:

```bash
uv run ohmo init \
  --workspace "$OHMO_WORKSPACE" \
  --no-interactive
```

Configure the gateway-facing provider selection:

```bash
uv run ohmo config \
  --workspace "$OHMO_WORKSPACE" \
  --cwd "$MANUAL_PROJECT"
```

For a local-only test:

1. choose **LM Studio (Anthropic)**;
2. leave Telegram, Slack, Discord, and Feishu disabled;
3. keep progress/tool-hint defaults as desired;
4. leave remote administrative commands disabled.

The wizard writes `$OHMO_WORKSPACE/gateway.json`. This provider selection belongs to the ohmo
gateway. Local `ohmo` commands below also pass `--profile lmstudio-anthropic` explicitly, so the
test does not depend on an implicit default.

Inspect workspace and provider readiness:

```bash
uv run ohmo doctor \
  --workspace "$OHMO_WORKSPACE" \
  --cwd "$MANUAL_PROJECT"

uv run ohmo gateway status \
  --workspace "$OHMO_WORKSPACE" \
  --cwd "$MANUAL_PROJECT"
```

Pass criteria:

- every workspace item reported by `doctor` is `ok`;
- `lmstudio-anthropic` appears as `configured`;
- gateway status reports `provider_profile: "lmstudio-anthropic"`;
- no channel is required for the local CLI/TUI checks.

## 8. Test headless ohmo and personal memory

Create an explicit personal-memory marker:

```bash
uv run ohmo memory add \
  manual-lmstudio-test \
  "Remember the marker OHMO_MEMORY_OK for this manual test." \
  --workspace "$OHMO_WORKSPACE"

uv run ohmo memory list --workspace "$OHMO_WORKSPACE"
```

Then make a one-shot ohmo request:

```bash
uv run ohmo \
  --workspace "$OHMO_WORKSPACE" \
  --cwd "$MANUAL_PROJECT" \
  --profile lmstudio-anthropic \
  --max-turns 4 \
  -p "What manual-test marker is in your personal memory? Reply with only the marker."
```

Expected final content:

```text
OHMO_MEMORY_OK
```

This proves the ohmo prompt includes its personal workspace memory while using the same
OpenHarness provider client. It does not prove project-memory injection; ohmo intentionally keeps
plain project memory disabled by default.

## 9. Test ohmo through the terminal frontend

Launch the shared React terminal with the ohmo backend:

```bash
uv run ohmo \
  --workspace "$OHMO_WORKSPACE" \
  --cwd "$MANUAL_PROJECT" \
  --profile lmstudio-anthropic
```

The process path is:

```text
uv run ohmo
  -> launch_ohmo_react_tui()
  -> tsx frontend/terminal/src/index.tsx
  -> python -m ohmo --backend-only
  -> shared OpenHarness runtime with ohmo overrides
```

Perform these interactions:

1. enter `/status` and confirm the expected model;
2. ask for the `OHMO_MEMORY_OK` marker and verify it is recalled;
3. ask a second question to verify the session continues;
4. enter `/exit` and confirm a clean terminal shutdown.

After a live turn, inspect `$OHMO_WORKSPACE/sessions/` to confirm ohmo—not the default OpenHarness
session backend—owns the saved conversation.

## 10. Optional channel gateway test

The local ohmo tests above intentionally configure no channels. Test the gateway only when a real
channel credential and authorized sender are available.

Re-run `uv run ohmo config`, enable one channel, and configure a restrictive `allow_from` list.
Then run the gateway in the foreground so logs remain visible:

```bash
uv run ohmo gateway run \
  --workspace "$OHMO_WORKSPACE" \
  --cwd "$MANUAL_PROJECT"
```

From another terminal using the same environment, inspect status:

```bash
uv run ohmo gateway status \
  --workspace "$OHMO_WORKSPACE" \
  --cwd "$MANUAL_PROJECT"
```

Send one authorized private message and verify progress, tool hints, and the final reply according
to the configured channel settings. Also send or simulate one unauthorized message and verify it is
rejected before model execution. Stop the foreground gateway with `Ctrl+C`.

## Failure localization

| First failing step | Inspect first |
| --- | --- |
| Direct `curl` | LM Studio version, server port, token, model ID, `/v1/messages` support |
| Profile reports missing auth | Keyring/fallback credential, `OPENHARNESS_CONFIG_DIR`, profile name |
| Dry-run selects another model | `oh setup`, active-profile marker, saved `settings.json` |
| Text-only `oh -p` fails | `AnthropicApiClient`, LM Studio SSE stream, context/token parameters |
| Text works but tool replay fails | Model tool-use support, LM Studio template, tool-call IDs/arguments |
| `uv run oh` fails before welcome | Node/npm dependencies, `react_launcher.py`, terminal TTY |
| TUI opens but backend exits | `OPENHARNESS_FRONTEND_CONFIG`, backend stderr, provider auth |
| ohmo doctor cannot see profile | Both commands must share `OPENHARNESS_CONFIG_DIR` |
| ohmo cannot recall marker | `OHMO_WORKSPACE`, memory file/index, ohmo prompt assembly |
| Plain `oh` sees ohmo memory | Workspace isolation regression; plain runtime must not inject ohmo memory |
| Gateway receives nothing | Channel credentials, `allow_from`, group/mention policy, gateway logs |

## State created by this runbook

| State | Location |
| --- | --- |
| Provider settings | `$OPENHARNESS_CONFIG_DIR/settings.json` |
| Fallback provider credentials | `$OPENHARNESS_CONFIG_DIR/credentials.json` |
| OpenHarness sessions/data | `$OPENHARNESS_DATA_DIR` |
| OpenHarness logs | `$OPENHARNESS_LOGS_DIR` |
| ohmo persona, memory, sessions, gateway config/logs | `$OHMO_WORKSPACE` |
| Tool-write smoke file | `$MANUAL_PROJECT/terminal-smoke.txt` |
| Possible system-keyring credential | service `openharness`, key `profile:lmstudio-anthropic:api_key` |

Only delete `$MANUAL_ROOT` after confirming it points to this scratch directory. Removing the
directory does not remove a credential stored in the operating-system keyring.

## Related implementation and tests

- [LM Studio provider setup](../providers/LM_STUDIO_ANTHROPIC.md)
- [React terminal protocol](../developer/flows/TERMINAL_UI_PROTOCOL.md)
- [ohmo integration flow](../developer/flows/OHMO_INTEGRATION.md)
- `src/openharness/cli.py` and `src/openharness/ui/app.py`
- `src/openharness/ui/react_launcher.py` and `src/openharness/ui/backend_host.py`
- `frontend/terminal/src/`
- `ohmo/cli.py` and `ohmo/runtime.py`
- `tests/test_ui/` and `tests/test_ohmo/`
