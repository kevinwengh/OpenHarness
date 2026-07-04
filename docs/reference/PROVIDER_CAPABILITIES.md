# Provider client capability matrix

Provider names are discovery and configuration labels; runtime behavior comes from the selected
client family, endpoint, and model. This matrix describes what each OpenHarness client can
translate or parse. “Transport-supported” does not prove that a compatible endpoint or selected
model accepts the feature.

| Client family | Text stream | Tool request/replay | Image input | Reasoning/thinking | Principal limit |
| --- | --- | --- | --- | --- | --- |
| Anthropic Messages (`AnthropicApiClient`) | yes | native schemas and stable `tool_use`/`tool_result` IDs | base64 Anthropic blocks | request/stream/replay not implemented | final parser ignores non-text/non-tool blocks |
| OpenAI Chat Completions (`OpenAICompatibleClient`) | yes | function calls assembled by stream index and replayed by ID | data-URL `image_url` | partial non-standard `reasoning_content` replay | endpoint variants and malformed arguments can be lossy |
| ChatGPT Codex Responses (`CodexApiClient`) | yes | completed function-call items and outputs | data-URL `input_image` | effort is sent; encrypted reasoning is not retained | intentionally restricted to the ChatGPT backend API |
| GitHub Copilot (`CopilotClient`) | delegated | delegated to the OpenAI-compatible adapter | delegated transport support | delegated conventions | token lifecycle and endpoint/model behavior remain Copilot-specific |

All four clients normalize into `ApiStreamEvent` values from
`src/openharness/api/client.py`. `src/openharness/engine/query.py::run_query()` then owns tool
validation, permission and hook checks, concurrent sibling execution, ordered result replay,
continuation, and persistence. A client reporting a stop reason does not by itself make the engine
execute tools; parsed `ToolUseBlock` values are the controlling signal.

## Selection and authentication

| Effective profile shape | Runtime selection | Authentication owner |
| --- | --- | --- |
| `provider=anthropic_claude` | Anthropic client in subscription mode | external Claude credential binding and token refresh |
| Anthropic-format API profile | Anthropic client | profile credential slot, keyring/file, or mapped environment variable |
| `provider=openai_codex` | Codex Responses client | external Codex CLI credential binding |
| `api_format=copilot` | Copilot wrapper | GitHub device flow and Copilot token exchange |
| `api_format=openai` or `openai_compat` | OpenAI-compatible client | profile credential slot, keyring/file, or mapped environment variable |

`src/openharness/ui/runtime.py::_resolve_api_client_from_settings()` is authoritative. The registry
in `src/openharness/api/registry.py` supplies detection and display metadata, not request routing.

## Compatibility must be tested in layers

For a new endpoint or model, verify separately:

1. authentication and the final base URL;
2. one text-only stream and usage extraction;
3. one tool request followed by its matching result and final answer;
4. two sibling tool requests, including one failure;
5. image input when claimed;
6. reasoning fields when the endpoint requires them;
7. retry, timeout, cancellation, and malformed-stream behavior; and
8. save/resume of a conversation containing tool calls.

A successful text response proves only the first response path. Use the detailed implementation
references for [Anthropic](../developer/providers/ANTHROPIC_CLIENT_INTEGRATION.md),
[OpenAI-compatible](../developer/providers/OPENAI_COMPATIBLE_CLIENT_INTEGRATION.md),
[Codex subscription](../developer/providers/CODEX_SUBSCRIPTION_INTEGRATION.md), and
[GitHub Copilot](../developer/providers/GITHUB_COPILOT_INTEGRATION.md).
