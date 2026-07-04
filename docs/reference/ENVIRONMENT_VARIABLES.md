# Environment-variable reference

Environment variables fall into three classes: public configuration, host/integration controls,
and internal test/worker protocol. Do not expose internal variables as stable public API without a
compatibility decision.

## Public configuration

| Variable | Purpose | Owner |
| --- | --- | --- |
| `OPENHARNESS_CONFIG_DIR` | relocate settings and credential root | `config/paths.py` |
| `OPENHARNESS_DATA_DIR` | relocate sessions/tasks/cron/feedback data | `config/paths.py` |
| `OPENHARNESS_LOGS_DIR` | relocate logs | `config/paths.py` |
| `OPENHARNESS_PROFILE` | select active provider profile | `config/settings.py::_apply_env_overrides()` |
| `OPENHARNESS_PROVIDER` | legacy/effective provider override | settings |
| `OPENHARNESS_MODEL` | model override | settings |
| `OPENHARNESS_API_FORMAT` | Anthropic/OpenAI/Copilot conversion | settings |
| `OPENHARNESS_BASE_URL` | endpoint override | settings |
| `OPENHARNESS_TIMEOUT` | provider timeout | settings |
| `OPENHARNESS_MAX_TOKENS` | completion-token request | settings |
| `OPENHARNESS_MAX_TURNS` | query turn limit | settings |
| `OPENHARNESS_CONTEXT_WINDOW_TOKENS` | token-window heuristic | settings |
| `OPENHARNESS_AUTO_COMPACT_THRESHOLD_TOKENS` | compaction threshold | settings |
| `OPENHARNESS_LOG_LEVEL` | logging verbosity | CLI/log setup |
| `OPENHARNESS_SANDBOX_ENABLED` | enable sandbox policy | settings |
| `OPENHARNESS_SANDBOX_BACKEND` | select sandbox backend | settings |
| `OPENHARNESS_SANDBOX_FAIL_IF_UNAVAILABLE` | fail instead of host fallback | settings |
| `OPENHARNESS_SANDBOX_DOCKER_IMAGE` | Docker image override | settings |
| `OPENHARNESS_WEB_PROXY` | explicit web-tool proxy | settings/web tools |
| `OPENHARNESS_WEB_RESOLUTION_MODE` | network-resolution policy | settings/network guard |
| `OPENHARNESS_WEB_SYNTHETIC_DNS_CIDRS` | synthetic-DNS ranges | settings/network guard |
| `OPENHARNESS_WEB_SEARCH_URL` | search endpoint override | web-search tool |
| `OPENHARNESS_CHANNEL_MEDIA_DIR` | override normalized channel-media root | channel base adapter |
| `OHMO_WORKSPACE` | personal workspace root | `ohmo/workspace.py` |

Provider-specific API-key variables are resolved in order by
`auth_source_env_var_candidates()`: the `OPENHARNESS_<PROVIDER>_API_KEY` form first, followed by the
provider-native form. The implemented providers are Anthropic, OpenAI, DashScope, Moonshot,
Gemini, MiniMax, NVIDIA, and ModelScope. Use `oh provider status` to see which source was found
without printing its value. There is no generic main-runtime `OPENHARNESS_API_KEY` override.

## Compatibility variables

When the active profile does not already set the corresponding value, `ANTHROPIC_MODEL` can supply
the model and `ANTHROPIC_BASE_URL` or `OPENAI_BASE_URL` can supply the endpoint. Explicit
`OPENHARNESS_MODEL` and `OPENHARNESS_BASE_URL` take precedence. `ANTHROPIC_AUTH_TOKEN` is used by
the Claude subscription/token path. External credential discovery also recognizes `CODEX_HOME`,
`CLAUDE_CONFIG_DIR`, and `CLAUDE_HOME`.

## Optional vision and image generation

`VisionModelConfig.from_env()` reads `OPENHARNESS_VISION_MODEL`,
`OPENHARNESS_VISION_API_KEY`, and `OPENHARNESS_VISION_BASE_URL`.
`ImageGenerationConfig.from_env()` reads `OPENHARNESS_IMAGE_GENERATION_PROVIDER`, `MODEL`,
`API_KEY`, `BASE_URL`, `CODEX_MODEL`, and `CODEX_BASE_URL`. These clients can send source images or
prompts to an endpoint separate from the main chat provider.

## Runtime tuning

The implementation also recognizes advanced tuning variables for image token estimates,
tool-output inline/preview limits, microcompaction size, and one provider-compatibility behavior.
They are implementation controls, not stable compatibility promises:

- `OPENHARNESS_IMAGE_TOKEN_ESTIMATE`
- `OPENHARNESS_TOOL_OUTPUT_INLINE_CHARS`
- `OPENHARNESS_TOOL_OUTPUT_PREVIEW_CHARS`
- `OPENHARNESS_MICROCOMPACT_TOOL_RESULT_CHARS`
- `OPENHARNESS_REQUIRE_EMPTY_REASONING_CONTENT`

## Frontend and hook protocols

| Variable | Producer → consumer | Stability |
| --- | --- | --- |
| `OPENHARNESS_FRONTEND_CONFIG` | Python launcher → Ink frontend | internal protocol |
| `OPENHARNESS_FRONTEND_SCRIPT` | tests/launcher → frontend resolution | internal/test |
| `OPENHARNESS_FRONTEND_RAW_RETURN` | frontend test path | internal/test |
| `OPENHARNESS_HOOK_EVENT` | hook executor → command hook | extension contract |
| `OPENHARNESS_HOOK_PAYLOAD` | hook executor → command hook | extension contract; JSON |

Hook payloads may contain raw tool arguments. Treat both variables as sensitive and hostile input.

## Worker and service protocols

Variables such as `OPENHARNESS_TEAMMATE_COMMAND`, `OPENHARNESS_TEAMMATE_MODE`,
`OPENHARNESS_AGENT_TEAMS`, and `OPENHARNESS_AUTODREAM_*` coordinate child processes. E2E variables
such as `OPENHARNESS_E2E_*` are test-only. They are not operator configuration and may change with
the spawning code.

## Precedence and security

Environment overrides apply after the saved settings file and before explicit CLI/runtime
overrides. An environment value can therefore change provider, endpoint, permission-adjacent
runtime behavior, or storage location for every child process that inherits it.

- Do not put secrets in shell scripts committed to a repository.
- Remember detached cron/gateway processes may have a different environment from an interactive
  shell.
- Use temporary root variables for tests to avoid reading or rewriting personal state.
- Redact environment dumps in bug reports.
