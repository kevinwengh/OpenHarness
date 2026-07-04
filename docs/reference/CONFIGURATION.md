# Configuration reference

This reference describes the current `openharness.config.settings.Settings` model and the separate
ohmo gateway configuration. Source remains authoritative because settings are not yet governed by a
formal compatibility policy.

## Resolution and precedence

For a normal runtime, `ui/runtime.py::build_runtime()` calls `load_settings()` and then
`Settings.merge_cli_overrides()`.

```text
Pydantic defaults
  → saved settings.json (including compatibility migration)
  → environment overrides
  → active provider profile materialization
  → explicit CLI/runtime overrides
  → injected client/backend/root overrides from the host
```

Provider profile materialization can replace flat `provider`, `model`, `api_format`, `base_url`,
and credential-selection fields. A flat value shown in the file is not necessarily the effective
runtime value. Use `oh config show`, `oh provider status`, or `oh --dry-run --output-format json` to
inspect redacted effective state.

## Configuration roots

| State | Default | Override | Owner |
| --- | --- | --- | --- |
| Settings/credentials | `~/.openharness` | `OPENHARNESS_CONFIG_DIR` | `config/paths.py::get_config_dir()` |
| Runtime data | `<config>/data` | `OPENHARNESS_DATA_DIR` | `get_data_dir()` |
| Logs | `<config>/logs` | `OPENHARNESS_LOGS_DIR` | `get_logs_dir()` |
| ohmo workspace | `~/.ohmo` | `OHMO_WORKSPACE` or CLI option | `ohmo/workspace.py::get_workspace_root()` |

## Top-level OpenHarness settings

| Field | Default | Purpose / important behavior |
| --- | --- | --- |
| `active_profile` | `claude-api` | Selects one entry in `profiles` |
| `profiles` | built-in profile map | Provider, wire format, auth source, model, endpoint, limits |
| `provider` | empty/derived | Detection label; does not alone choose a client contract |
| `model` | `claude-sonnet-4-6` | Effective model after profile/override merge |
| `api_format` | `anthropic` | Selects Anthropic, OpenAI-compatible, or Copilot conversion |
| `api_key` | empty | Legacy flat secret; prefer credential storage/environment |
| `base_url` | provider default | Optional endpoint override |
| `timeout` | `30.0` | Provider HTTP timeout where supported |
| `max_tokens` | `16384` | Requested completion budget; query loop may clamp/retry |
| `max_turns` | `200` | Maximum model turns for an enforced query |
| `context_window_tokens` | unset | Explicit context estimate override |
| `auto_compact_threshold_tokens` | unset | Explicit compaction threshold override |
| `system_prompt` | unset | Replaces/extends runtime prompt according to CLI path |
| `permission` | nested defaults | mode plus tool/path/command policy |
| `hooks` | `{}` | lifecycle hook definitions |
| `memory` | nested defaults | context, extraction, session memory, autodream |
| `sandbox` | disabled | backend, availability policy, network/filesystem/Docker settings |
| `web` | defaults | proxy, resolution mode, synthetic DNS ranges |
| `enabled_plugins` | `{}` | per-plugin enabled state |
| `allow_project_plugins` | `false` | executable project-plugin trust gate |
| `allow_project_skills` | `true` | project instruction discovery gate |
| `project_skill_dirs` | three compatibility roots | safe relative skill directories |
| `mcp_servers` | `{}` | stdio/HTTP/WebSocket server definitions |
| `theme` | `default` | persisted terminal theme |
| `output_style` | `default` | response presentation style |
| `vim_mode`, `voice_mode`, `fast_mode` | `false` | interactive behavior toggles |
| `effort` | `medium` | provider reasoning effort where supported |
| `passes` | `1` | repeated reasoning/workflow passes |
| `verbose` | `false` | diagnostic verbosity |
| `vision`, `image_generation` | nested defaults | optional secondary model clients |

Exact field definitions and validators are in `config/settings.py::Settings`,
`PermissionSettings`, `MemorySettings`, `SandboxSettings`, `WebSettings`, `VisionModelConfig`, and
`ImageGenerationConfig`.

## Provider profiles

`ProviderProfile` fields are:

| Field | Meaning |
| --- | --- |
| `label` | user-facing name |
| `provider` | registry/detection family |
| `api_format` | wire-conversion family |
| `auth_source` | environment/storage/subscription selector |
| `default_model` / `last_model` | model selection and remembered choice |
| `base_url` | endpoint override |
| `credential_slot` | isolates custom-profile credentials |
| `allowed_models` | picker hints, not proof of endpoint support |
| context/compaction limits | profile-specific token heuristics |

Resolution functions include `Settings.resolve_profile()`, `materialize_active_profile()`,
`resolve_auth()`, and `resolve_api_key()`. Client selection remains in `ui/runtime.py`, so a profile
name alone is not a compatibility guarantee.

## Permission settings

`PermissionChecker.evaluate()` applies policy in this order after tool validation and metadata
extraction:

1. built-in sensitive credential paths;
2. `denied_tools`;
3. `allowed_tools`;
4. denying `path_rules`;
5. `denied_commands` patterns;
6. `full_auto` mode;
7. read-only classification;
8. plan-mode denial;
9. default-mode confirmation.

An explicit allowed tool does not override the built-in sensitive-path step because that check
occurs first.

## Sandbox settings

`SandboxSettings` owns `enabled`, `backend`, `fail_if_unavailable`, platform filters, network and
filesystem policy, and Docker settings. Docker configuration includes image, auto-build, CPU/memory
limits, extra mounts, and extra environment variables.

Sandbox routing is tool-specific, and `sandbox/session.py` currently stores one module-global active
Docker session. Do not assume multiple sandbox-enabled runtime bundles in one process are isolated.

## Memory settings

`MemorySettings` controls maximum prompt files/index bounds, token heuristics, automatic extraction,
session-memory checkpoints, and autodream cadence. These are input bounds and feature gates, not a
retention policy.

## ohmo gateway configuration

ohmo uses `ohmo/gateway/config.py` and `openharness.config.schema.Config`, separate from core
`Settings`. It selects a provider profile/model, progress behavior, remote administrative-command
policy, and channel configurations. `ohmo config` currently guides Telegram, Slack, Discord, and
Feishu setup; the compatibility schema and manager contain additional adapters.

`gateway.json` contains channel tokens/secrets in plaintext. Changes used by an already running
gateway may require the config flow's restart path or `ohmo gateway restart`.

## Mutating configuration safely

- Prefer `oh setup`, `oh provider`, `oh auth`, and `oh config` to hand-editing JSON.
- Use `save_settings()`, which synchronizes profile/flat fields, locks, and writes atomically.
- Never print or commit unredacted settings.
- Test configuration changes under temporary config/data/log roots.
- Cover default, saved, environment, profile, and CLI precedence in tests.
