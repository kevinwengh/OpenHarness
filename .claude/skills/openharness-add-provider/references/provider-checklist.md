# Provider compatibility checklist

## Discovery and configuration

- Registry order and canonical name
- Model keywords, key prefix, and base URL detection
- Default base URL and environment variable
- Gateway/local/OAuth classification
- Default profile and auth-source mapping if first-class
- Saved settings, environment, profile, and CLI precedence

## Client behavior

- Request URL and authentication headers
- System prompt and message conversion
- Tool schema conversion and tool-choice behavior
- Reasoning/effort parameters
- Image/input block conversion where supported
- Streaming text and reasoning deltas
- Incremental tool-call ID/name/arguments
- Finish reason and usage accounting
- Timeout, rate limit, auth, and malformed-response errors

## Multi-turn invariants

- Assistant text plus tool calls serialize correctly
- Provider-required reasoning content is retained on replay
- Tool results reference the correct call ID
- Multiple/parallel tool calls preserve ordering and IDs
- Conversation sanitization does not drop required fields

## UX and safety

- Setup/profile labels and defaults
- Auth login/status/logout when applicable
- `oh --dry-run --output-format json` reports actionable readiness
- Diagnostics redact keys and tokens
- README claims match tested capabilities

## Tests

- `tests/test_api/`
- `tests/test_auth/`
- `tests/test_config/test_settings.py`
- relevant CLI/entrypoint/runtime tests
- engine tool-loop test when replay semantics change
- optional real API eval only under `harness-eval`
