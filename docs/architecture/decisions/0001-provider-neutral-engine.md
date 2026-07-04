# ADR-0001: Provider-neutral engine and normalized streams

## Status

Accepted; implemented by `api/client.py`, provider clients, `engine/messages.py`, and
`engine/query.py`.

## Context

Anthropic Messages, OpenAI-compatible chat completions, Codex Responses, and Copilot differ in auth,
request shape, streaming events, reasoning, tool calls, usage, and replay. Forking the engine per API
would also fork permissions, hooks, tools, compaction, persistence, and UIs.

## Decision

The engine supplies provider-neutral `ApiMessageRequest` values containing normalized conversation
blocks. Provider clients translate those requests to wire messages and translate responses into
normalized stream events plus `ApiMessageCompleteEvent`. The engine owns one model/tool lifecycle
independent of the wire client.

## Alternatives

- provider-specific agent loops: rejected due duplicated safety/state behavior;
- lowest-common-denominator text API: rejected because tools, images, reasoning, and usage matter;
- expose raw SDK events to hosts: rejected because every UI/persistence layer would become provider-aware.

## Consequences

One governance and rendering path serves every provider. The cost is adapter complexity and possible
loss when a provider capability does not fit normalized blocks. Compatibility requires request,
stream, replay, error, usage, and cleanup tests—not a provider-name match.

## Revisit when

A provider capability cannot be represented without corrupting replay or forcing provider policy
into the shared engine. Prefer extending normalized contracts before forking the loop.
