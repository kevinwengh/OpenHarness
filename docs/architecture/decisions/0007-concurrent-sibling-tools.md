# ADR-0007: Concurrent sibling tool execution with ordered replay

## Status

Accepted; implemented in `engine/query.py::run_query()`.

## Context

A model can request multiple independent tools in one assistant message. Serial execution adds
latency, but provider replay requires one result for every tool-use ID in a valid deterministic
message.

## Decision

Execute a single tool inline for immediate events. For multiple sibling calls, emit start events,
run `_execute_tool_call()` instances with `asyncio.gather(return_exceptions=True)`, normalize every
exception into a matching error result, emit completions in request order, and append one ordered
user tool-result message.

## Alternatives

- always serial: simpler conflicts/events but unnecessary cumulative I/O latency;
- yield completions in finish order: lower streaming latency but nondeterministic replay/UI order;
- cancel siblings on one failure: invalidates provider history when tool-use results are missing.

## Consequences

Independent work is faster and replay stays valid. Mutating siblings can race on the same file,
process, or external resource because permissions are not transaction isolation. Completion events
for parallel calls arrive after gather, not at actual finish time.

## Revisit when

Tools declare effect/resource scopes sufficient to detect conflicts or streaming completion latency
becomes more important than deterministic grouping.
