# ADR-0006: Runtime bundle per gateway conversation key

## Status

Accepted; implemented by `ohmo/gateway/runtime.py::OhmoSessionRuntimePool`.

## Context

Long-lived channel conversations need isolated history, prompt context, tool metadata, and session
restore while avoiding a cold runtime for every message.

## Decision

Derive a session key from channel/account/chat/thread/sender scope and cache one `RuntimeBundle` per
active key. Restore its latest keyed snapshot lazily and reuse until cwd/config refresh or shutdown.
The gateway bridge serializes/cancels same-key processing.

## Alternatives

- one global runtime: rejected due cross-conversation context leakage;
- runtime per message: stronger isolation but high startup cost and weaker in-memory continuity;
- external session service: not required for current local single-process deployment.

## Consequences

Different keys can progress concurrently and same-key context remains warm. The pool is process-local
and currently unbounded with no idle eviction. It depends on bridge serialization and file snapshots
for restart recovery; multi-host ownership is undefined.

## Revisit when

Measured deployments require bounded capacity, eviction, durable queues, multi-process workers, or
multi-host coordination.
