# Compatibility and evolution policy

OpenHarness is pre-1.0 software. This document distinguishes supported user-facing contracts from
internal implementation so contributors can evolve the system without implying that every import or
persisted dictionary is stable forever.

## Compatibility classes

| Class | Examples | Current expectation |
| --- | --- | --- |
| User CLI | documented `oh`/`ohmo` flags and subcommands | avoid removal/semantic change without changelog and migration guidance |
| Extension contract | `BaseTool`, skill layout, plugin manifest, hooks, MCP config, `SessionBackend`, `BaseChannel` | preserve documented fields and behavior within a release line; add tests for changes |
| Provider protocol | `SupportsStreamingMessages`, `ApiMessageRequest`, normalized events/messages | preserve engine-facing semantics; adapters may add provider-specific compatibility behavior |
| Persisted state | settings, memory, sessions, cron, autopilot, ohmo workspace | load existing supported files or fail with an actionable version/migration error |
| UI protocol | `FrontendRequest`, `BackendEvent`, `OHJSON:` pipe framing | Python and TypeScript change together; currently internal and unversioned |
| Python implementation | unlisted modules/classes/functions | internal unless this or public docs explicitly designate them |

## Public Python surface

The package currently has no exhaustive stable Python SDK declaration. Treat direct imports as
internal unless they are documented extension points in `docs/EXTENDING.md` or this policy. The
minimum intended extension surfaces are:

- `openharness.tools.base.BaseTool`, `ToolExecutionContext`, and `ToolResult`;
- `openharness.services.session_backend.SessionBackend`;
- channel `BaseChannel` plus normalized bus events for adapter work;
- provider streaming request/event/message contracts used by an added client;
- hook event names and validated hook schemas;
- plugin/skill manifest and layout formats.

`RuntimeBundle`, `QueryEngine`, command internals, registries, and composition helpers are reusable
inside this repository but should not be assumed stable for third-party libraries without an
explicit promotion decision.

## Change rules

### Additive changes

Prefer optional fields with defaults, new event variants handled defensively, and new commands/tools
with unique names. Ensure older persisted input remains valid when practical.

### Breaking changes

A breaking change includes removing/renaming a field or command, changing precedence, changing a
persisted enum, changing tool replay shape, changing session-key derivation, or making previously
safe configuration executable. It requires:

1. documented rationale and affected contracts;
2. changelog entry and release note;
3. migration or explicit unsupported-version diagnostic;
4. old-format fixtures and tests;
5. updates to provider, UI, extension, and operator documentation;
6. deprecation period when user impact justifies it.

## Persisted formats

Memory already has explicit schema and migration machinery. Other formats mostly rely on Pydantic
defaults, compatibility loaders, sanitization, or tolerant reads. Contributors should not silently
reinterpret old data.

New evolving formats should include a version field, an owning loader, idempotent migration, a
backup strategy, and tests using previously released fixtures. See
[State and persisted formats](reference/STATE_AND_PERSISTED_FORMATS.md).

## Provider compatibility

A registry label or model name is not proof of compatibility. A provider/profile claim requires
evidence for:

- authentication and endpoint resolution;
- request/message conversion;
- streamed visible text and final message assembly;
- reasoning/thinking behavior where exposed;
- tool schema, streamed calls, results, and multi-turn replay;
- image handling;
- usage and finish reasons;
- retry, error translation, cancellation, and cleanup.

The detailed provider guides under `docs/developer/providers` are the current evidence map.

## Extension compatibility

Plugin Python code runs in-process and is tightly coupled to Python APIs. Manifest, Markdown skill,
command, and hook formats are better candidates for stable contracts. When plugin APIs evolve,
diagnostics should identify plugin name/path and unsupported field/version rather than failing
silently during import.

## Deprecation template

A deprecation notice should state the old behavior, replacement, first deprecated version, planned
removal version or condition, migration example, and detection command. Runtime warnings must never
print secrets or flood every model turn.
