# Tool contract checklist

## Contract

- Stable unique tool name
- Description states when to use the tool and what it returns
- Pydantic fields have useful descriptions, constraints, and safe defaults
- Output is concise enough to return to the model
- Expected failures return `ToolResult(is_error=True)` with actionable text

## Execution

- Async implementation does not block the loop with long synchronous work
- Paths resolve from `context.cwd`
- External inputs and URLs are validated
- Timeouts and output limits exist for unbounded operations
- Temporary resources and subprocesses are cleaned up

## Governance

- `is_read_only()` is conservative and argument-aware
- Permission evaluation receives path/command context where applicable
- Sensitive paths cannot be bypassed through alternate path forms
- Docker sandbox behavior is explicit
- Pre/post hooks still wrap execution
- Secrets are absent from output, metadata, and logs

## Integration

- Built-in tool is registered in `tools/__init__.py`
- Plugin tool export matches loader expectations
- Runtime metadata dependencies are documented and populated
- Stream/tool-result messages remain serializable and resumable

## Tests

- Schema, success, invalid input, normalized failure
- Read-only/mutating classification
- Permission deny/confirm/allow cases
- Hook/sandbox behavior if applicable
- Registry or plugin loading
- Engine continuation for lifecycle-sensitive tools
