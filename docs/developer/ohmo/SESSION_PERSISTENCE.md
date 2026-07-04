# Session persistence and isolation

## Files and pointers

The backend is rooted at `<workspace>/sessions` regardless of project CWD. `get_session_dir()` is at
[`ohmo/session_storage.py:35`](../../../ohmo/session_storage.py#L35).

Each save can write three copies:

```text
latest.json                         global latest pointer
latest-<12-char SHA1>.json          latest for a gateway session key
session-<session_id>.json           durable ID-addressed snapshot
```

The session-key token is the first 12 hex characters of SHA-1 at
[`session_storage.py:51`](../../../ohmo/session_storage.py#L51). The hash hides raw channel IDs from
filenames but is not a security primitive or collision-proof namespace.

## Snapshot payload

`save_session_snapshot()` begins at
[`session_storage.py:81`](../../../ohmo/session_storage.py#L81). It sanitizes conversation messages,
finds the first non-empty user text for an 80-character summary, filters tool metadata through the
core persistence helper, and atomically writes JSON containing:

```text
app, session_id, session_key, cwd, model, system_prompt,
messages, usage, tool_metadata, created_at, summary, message_count
```

Message sanitization removes empty assistant messages and malformed dangling tool turns before
serialization. Tool metadata is restricted to core persistable fields; runtime-only objects must
not be assumed to survive.

The three writes are individually atomic but not one transaction. A crash can leave their pointers
at different revisions.

## Load paths

- `load_latest()` reads global `latest.json` at
  [`session_storage.py:137`](../../../ohmo/session_storage.py#L137).
- `load_latest_for_session_key()` reads only the hashed session pointer at
  [`session_storage.py:155`](../../../ohmo/session_storage.py#L155); it does not fall back to global
  latest, preventing cross-chat restore.
- `load_by_id()` reads `session-ID.json` and then accepts global latest when IDs match or the caller
  requests `latest` at [`session_storage.py:206`](../../../ohmo/session_storage.py#L206).
- `list_snapshots()` skips corrupt/unreadable ID files and returns lightweight metadata ordered by
  modification time at [`session_storage.py:173`](../../../ohmo/session_storage.py#L173).

Direct `load_latest`, keyed load, and ID load do not catch JSON decode or I/O errors locally; only
listing is tolerant. Their payloads pass through core `_sanitize_snapshot_payload()`.

## Backend adapter

`OhmoSessionBackend` implements the core `SessionBackend` protocol at
[`session_storage.py:254`](../../../ohmo/session_storage.py#L254). Its `cwd` parameters are accepted
for interface compatibility but storage remains workspace-global. This is why plain OpenHarness and
ohmo session stores are not interchangeable.

Markdown export writes one `transcript.md` containing text blocks only at
[`session_storage.py:227`](../../../ohmo/session_storage.py#L227). Tool calls/results and images are
not rendered in the transcript.

## Gateway restore isolation

The runtime pool loads only `load_latest_for_session_key(session_key)` when creating a bundle at
[`gateway/runtime.py:266`](../../../ohmo/gateway/runtime.py#L266). A private or shared-chat routing
key therefore selects its own pointer. Tests verify that one Slack thread sender and one Feishu
group sender cannot restore another's messages at
[`test_gateway.py:224`](../../../tests/test_ohmo/test_gateway.py#L224) and
[`test_gateway.py:673`](../../../tests/test_ohmo/test_gateway.py#L673).

On restore, snapshot messages and group-command metadata are sanitized before `build_runtime()` at
[`gateway/runtime.py:281`](../../../ohmo/gateway/runtime.py#L281). If the snapshot has a session ID,
the newly built bundle reuses it.

## Save timing

The gateway saves after normal engine completion, max-turn termination, command continuation, and
non-submitting command results. `_save_snapshot()` begins at
[`gateway/runtime.py:764`](../../../ohmo/gateway/runtime.py#L764). It removes internal `/group`
prompt material from both messages and tool metadata before delegating to the backend.

Cancellation can interrupt `_stream_engine_message()` before its normal save point. The bridge logs
and re-raises cancellation at [`gateway/bridge.py:422`](../../../ohmo/gateway/bridge.py#L422); there
is no unconditional snapshot in a `finally` block.

## Tests and change checklist

Backend path, keyed restore, metadata, and legacy empty-message sanitation are tested in
[`test_ohmo_session_storage.py:11`](../../../tests/test_ohmo/test_ohmo_session_storage.py#L11).
Gateway isolation and refresh sanitation have broader cases in
[`test_gateway.py:481`](../../../tests/test_ohmo/test_gateway.py#L481) and
[`test_gateway.py:3108`](../../../tests/test_ohmo/test_gateway.py#L3108).

Preserve pointer isolation, atomic writes, message/tool pairing, metadata filtering, legacy payload
sanitation, and explicit behavior for cancellation/corruption when changing persistence.
