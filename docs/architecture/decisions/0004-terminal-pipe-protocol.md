# ADR-0004: Local pipe protocol for the React terminal

## Status

Accepted; detailed in [Frontend/backend IPC](../frontend_backend_ipc.md).

## Context

The Ink frontend needs an interactive terminal while Python owns runtime, credentials, tools, and
persistence. The topology is one local frontend and one backend child.

## Decision

The Python launcher starts the TypeScript/Ink process, passes bootstrap config through
`OPENHARNESS_FRONTEND_CONFIG`, and the frontend spawns `oh --backend-only`. Requests are newline JSON
on stdin; backend events are `OHJSON:`-prefixed JSON on stdout.

## Alternatives

- WebSocket/HTTP server: unnecessary port, auth, discovery, and cleanup for one local client;
- embed Node/Python in one runtime: packaging/TTY complexity;
- Python-only UI: retained as alternative but not the primary React experience.

## Consequences

The process tree is simple and has no listening socket. The protocol is local, single-client,
unversioned, manually mirrored in Python/TypeScript, and lacks reconnect/replay/backpressure
negotiation. It must not be treated as a remote API.

## Revisit when

Remote/multiple/reconnecting clients become a real requirement. Define versioned authentication and
transport semantics rather than exposing the internal pipe framing directly.
