# Use LM Studio through the Anthropic-compatible API

This guide configures OpenHarness to send Anthropic Messages API requests to a model served
locally by LM Studio. It uses an OpenHarness provider profile, so switching back to another
provider does not require editing global settings.

## Request path

```text
oh
  -> active provider profile: lmstudio-anthropic
  -> api_format: anthropic
  -> AnthropicApiClient
  -> Anthropic Python SDK
  -> POST http://localhost:1234/v1/messages
  -> model loaded by LM Studio
```

OpenHarness passes the profile's base URL directly to the Anthropic SDK. LM Studio's documented
Anthropic base URL is `http://localhost:1234`; the SDK adds the `/v1/messages` resource path. Do
not configure the profile base URL as the complete `/v1/messages` endpoint.

## Prerequisites

1. Install LM Studio 0.4.1 or newer. LM Studio introduced `POST /v1/messages` in 0.4.1.
2. Download and load a chat model in LM Studio.
3. Note the exact model identifier shown by LM Studio. The profile's `--model` value must match it.
4. Start the local server from LM Studio's Developer tab, or run:

   ```bash
   lms server start --port 1234
   ```

LM Studio documents the endpoint and current examples in its
[Anthropic compatibility guide](https://lmstudio.ai/docs/developer/anthropic-compat) and
[Messages API reference](https://lmstudio.ai/docs/developer/anthropic-compat/messages).

## Create the OpenHarness profile

When LM Studio's **Require Authentication** setting is disabled, create the profile with a harmless
placeholder key. OpenHarness uses the key to satisfy its API-key provider workflow; LM Studio
ignores it when authentication is disabled.

```bash
oh provider add lmstudio-anthropic \
  --label "LM Studio (Anthropic)" \
  --provider anthropic \
  --api-format anthropic \
  --auth-source anthropic_api_key \
  --model "YOUR_LM_STUDIO_MODEL_ID" \
  --base-url http://localhost:1234 \
  --api-key lmstudio
```

Replace `YOUR_LM_STUDIO_MODEL_ID` with the exact LM Studio identifier, for example:

```text
ibm/granite-4-micro
```

The fields have distinct responsibilities:

| Field | Purpose |
| --- | --- |
| `lmstudio-anthropic` | Stable local name for switching to this profile |
| `--provider anthropic` | Selects the Anthropic runtime client |
| `--api-format anthropic` | Serializes messages, tools, and results in Anthropic format |
| `--auth-source anthropic_api_key` | Resolves an API key for the Anthropic SDK |
| `--model` | Sends LM Studio's exact model identifier in every request |
| `--base-url http://localhost:1234` | Points the SDK at the local LM Studio server |
| `--api-key lmstudio` | Stores a profile-scoped placeholder credential |

Custom API-key profiles receive their own credential slot by default. The placeholder or token is
therefore associated with `lmstudio-anthropic` instead of replacing the credential used by the
built-in `claude-api` profile.

### When LM Studio authentication is enabled

Create an LM Studio API token and pass that token instead of the placeholder. Referencing an
environment variable keeps the literal token out of the command saved in shell history:

```bash
export LM_API_TOKEN="your-lm-studio-token"

oh provider add lmstudio-anthropic \
  --label "LM Studio (Anthropic)" \
  --provider anthropic \
  --api-format anthropic \
  --auth-source anthropic_api_key \
  --model "YOUR_LM_STUDIO_MODEL_ID" \
  --base-url http://localhost:1234 \
  --api-key "$LM_API_TOKEN"

unset LM_API_TOKEN
```

LM Studio accepts the `x-api-key` header emitted by the Anthropic SDK. Do not put a real token in
documentation, checked-in configuration, terminal transcripts, or issue reports.

## Activate and verify the profile

Activate the saved profile:

```bash
oh provider use lmstudio-anthropic
oh provider list
```

The active entry should resemble:

```text
* lmstudio-anthropic: LM Studio (Anthropic) [ready]
    auth=anthropic_api_key model=YOUR_LM_STUDIO_MODEL_ID base_url=http://localhost:1234
```

Inspect the resolved OpenHarness configuration without making a model request:

```bash
oh --dry-run --output-format json -p "Check the local provider"
```

Then make a minimal request:

```bash
oh -p "Reply with exactly: LM Studio is connected"
```

Start a normal interactive session after the one-shot request succeeds:

```bash
oh
```

## Verify LM Studio independently

If OpenHarness reports a provider error, isolate the server from the client by calling LM Studio
directly. This example assumes authentication is disabled; substitute the real token when it is
enabled.

```bash
curl http://localhost:1234/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: lmstudio" \
  -d '{
    "model": "YOUR_LM_STUDIO_MODEL_ID",
    "max_tokens": 64,
    "messages": [
      {"role": "user", "content": "Reply with: server ready"}
    ]
  }'
```

If this request fails, correct the LM Studio server, authentication, or model selection before
debugging OpenHarness.

## Tools and agent behavior

LM Studio's Anthropic-compatible Messages endpoint accepts streaming requests and custom tool
schemas. OpenHarness consequently sends its normal tool definitions and replays tool results through
the same agent loop used with other Anthropic-compatible providers.

Endpoint support alone does not guarantee that every local model will call tools correctly. Choose
a model and prompt template with tool-use support, then verify at least one multi-turn tool call
before relying on the profile for coding-agent work. Text-only success does not prove tool calling,
parallel calls, vision, reasoning fields, or long-context behavior.

## Change the model or token

Update the model after loading a different one in LM Studio:

```bash
oh provider edit lmstudio-anthropic \
  --model "NEW_LM_STUDIO_MODEL_ID" \
  --allowed-model "NEW_LM_STUDIO_MODEL_ID"
```

Replace an authentication token:

```bash
export LM_API_TOKEN="new-lm-studio-token"
oh provider edit lmstudio-anthropic --api-key "$LM_API_TOKEN"
unset LM_API_TOKEN
```

Use `oh provider use <name>` to switch between this profile and any other configured provider.

## Troubleshooting

| Symptom | Likely cause | Check |
| --- | --- | --- |
| Connection refused | LM Studio server is stopped or uses another port | Start the server and verify the Developer-tab port |
| HTTP 404 | Old LM Studio version or an incorrect base URL | Upgrade to 0.4.1+ and use `http://localhost:1234` |
| HTTP 401/403 | Authentication setting and stored token disagree | Replace the profile key with the current LM Studio token |
| Model not found | Profile uses a display name instead of the API model ID | Copy the exact identifier shown by LM Studio |
| Text works but tools fail | Model or prompt template does not reliably support tool use | Select a tool-capable model and test a simple tool call |
| Context overflow | Local model context is smaller than the profile assumption | Reduce conversation size or set profile context limits |
| Wrong provider receives requests | The LM Studio profile is not active | Run `oh provider use lmstudio-anthropic` and check `oh provider list` |

For runtime tracing, inspect:

- [`ProviderProfile`](../../src/openharness/config/settings.py) for profile and credential resolution;
- [`build_runtime()`](../../src/openharness/ui/runtime.py) for client selection;
- [`AnthropicApiClient`](../../src/openharness/api/client.py) for Anthropic SDK construction;
- [`run_query()`](../../src/openharness/engine/query.py) for streaming and tool-result replay.
