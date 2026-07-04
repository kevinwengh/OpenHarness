# ADR-0002: Local file persistence with atomic replacement

## Status

Accepted. Detailed behavior is in [State, concurrency, and recovery](../STATE_CONCURRENCY_AND_RECOVERY.md).

## Context

OpenHarness targets local CLI and personal-agent use without requiring a database or broker.
Settings, sessions, memory, tasks, cron, mailboxes, and autopilot need inspectable durable state.

## Decision

Store durable state under user/project/workspace roots. Rewrite important files using
`utils/fs.py::atomic_write_text()` and protect shared read-modify-write sections with
`utils/file_lock.py::exclusive_file_lock()`.

## Alternatives

- embedded database: stronger transactions/querying but more migration/backup complexity;
- hosted database/broker: unsuitable as a default local dependency;
- naive direct writes: rejected because crashes can truncate critical JSON.

## Consequences

State is portable and inspectable. Individual writes can be crash-safe and cooperating writers can
serialize. There are no cross-file transactions, distributed leases, global retention, or multi-host
active/active semantics. Snapshot pointers can disagree after a crash between writes.

## Revisit when

Measured contention, data volume, query needs, or multi-host deployment exceeds a documented local
file envelope. Migrate only the state requiring stronger semantics.
