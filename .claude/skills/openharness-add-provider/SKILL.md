---
name: openharness-add-provider
description: Add, modify, debug, or review an OpenHarness model provider, provider profile, authentication flow, API client, model capability heuristic, or compatibility translation. Use for OpenAI-compatible endpoints, Anthropic-compatible endpoints, Codex or Claude subscription auth, Copilot, provider detection, streamed response parsing, tool-call replay, setup UX, and provider tests.
---

# Add an OpenHarness provider

Trace the provider from configuration through multi-turn streaming behavior. Provider detection alone is not sufficient.

## Classify the change

- **Registry-only:** the endpoint uses existing OpenAI-compatible behavior and API-key auth.
- **First-class workflow:** existing wire behavior, but setup/profile defaults and documentation need a named workflow.
- **Protocol/auth change:** new request/stream translation, OAuth/subscription binding, or distinct capability behavior.

Read `docs/ARCHITECTURE.md`, the provider section of `docs/EXTENDING.md`, and [references/provider-checklist.md](references/provider-checklist.md).

## Implement

1. Add or update `ProviderSpec` in `src/openharness/api/registry.py`; preserve intentional detection priority.
2. Add default profile/auth-source behavior in `config/settings.py` only when required.
3. Add credential/auth flows under `auth/` or the provider-specific API module; never log tokens.
4. Implement or update the streaming client contract from `api/client.py` when wire behavior differs.
5. Route a distinct client in `_resolve_api_client_from_settings()` only when an existing client cannot represent it.
6. Update setup, profile, auth status, dry-run, and diagnostics paths for a first-class workflow.
7. Update model capability heuristics only with evidence; unknown models should keep conservative behavior.
8. Keep user-provided compatible endpoints possible without requiring a hard-coded registry entry.

## Verify

1. Test provider detection by model, key prefix, and base URL without stealing higher-priority matches.
2. Test settings/profile precedence and credential resolution with isolated temporary config.
3. Test request conversion, system/messages, tools, effort/thinking fields, and API errors.
4. Test streamed text, thinking/reasoning, tool-call argument assembly, finish states, and usage.
5. Test a multi-turn tool call: assistant tool request is replayed with required provider-specific fields, then a tool result is accepted.
6. Test auth/setup/dry-run output and verify secrets are redacted.
7. Run API, auth, config, CLI/runtime, and engine tests affected by the path.
8. Use `harness-eval` for real API validation only when explicitly requested or needed to establish compatibility; never place live credentials in tests.
9. Update README compatibility tables, development docs, and changelog for user-visible support.

## Avoid false compatibility claims

- Do not infer tool support, vision, reasoning, or context limits from brand alone.
- Do not claim support after a single text-only response.
- Do not treat a gateway as the underlying model provider when behavior depends on both.
- Do not special-case a provider in several call sites when a registry or client boundary owns the behavior.
