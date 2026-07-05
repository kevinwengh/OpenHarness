# `oh` and `ohmo`: shared concepts, different ownership

`oh` and `ohmo` use the same OpenHarness engine, but they are not two aliases for the same
application. `oh` is the coding-agent CLI/runtime scoped primarily by a working directory.
`ohmo` is a personal-agent application that adds a persistent workspace, persona, personal memory,
workspace sessions, and multi-channel gateway around that runtime.

This guide compares every major concept the two applications overlap on. It gives special attention
to memory because “memory,” conversation history, session snapshots, session-memory checkpoints,
compaction, extraction, and consolidation are related but not interchangeable.

## The shortest accurate mental model

```text
oh
  project cwd
    -> core prompt + project instructions + relevant project memory
    -> shared RuntimeBundle / QueryEngine / tools / compaction
    -> project-keyed session snapshots

ohmo
  personal workspace + an effective cwd
    -> ohmo persona + personal memory snapshot + core dynamic context
    -> the same RuntimeBundle / QueryEngine / tools / compaction
    -> workspace session snapshots; gateway snapshots also keyed by conversation
```

The product dependency is `ohmo` to `openharness`: `ohmo` specializes composition inputs and
persistence adapters, while the core runtime still owns provider calls, tool execution, permissions,
hooks, compaction, and most commands.

## Comparison at a glance

| Concept | `oh` | `ohmo` | Shared owner or important distinction |
| --- | --- | --- | --- |
| Primary identity | Coding agent in one cwd/project | Personal agent in one workspace | `ohmo` adds soul, identity, user profile, and bootstrap files |
| Tool scope | Current `--cwd` | Current `--cwd`; managed groups may select another cwd | Tools still operate through core runtime |
| Settings | OpenHarness settings/profile | Same settings/profile system; gateway selects a profile in `gateway.json` | Provider credentials remain OpenHarness-owned |
| System prompt | Core prompt, environment, project instructions, skills, relevant project memory | ohmo persona/personal-memory base plus core environment, project instructions, and skills; project memory disabled by default | Prompt construction is related but not identical |
| Durable memory | Project-scoped Markdown store | Workspace-scoped personal Markdown store | Both reuse schema/scanner and `/memory` adapter primitives |
| Conversation context | Engine messages | Same engine messages, one engine per local session or gateway key | Same compaction algorithm |
| Session-memory checkpoint | Core data directory, keyed by cwd and engine session ID | Currently the same core path logic, not the ohmo workspace | This is a current isolation gap |
| Session snapshots | Project-hashed OpenHarness session directory | `<workspace>/sessions`; gateway adds a session-key index | Different `SessionBackend` implementations |
| Memory extraction | Manual and optional automatic project-memory extraction | Manual `/memory extract` is rejected; optional engine auto-extraction still targets project memory | Current automatic-extraction mismatch |
| Memory consolidation | `/dream` over project memory/session snapshots | `/dream` and auto-dream are pointed at personal memory/workspace snapshots | Shared consolidation service with injected directories/runner |
| Commands | Core command registry | Same registry plus gateway authorization/intercepts | Not every core memory subcommand is rebound to personal state |
| Skills/plugins | Bundled, user, project, enabled plugin roots | Same roots plus workspace skill/plugin roots | Project plugin trust setting still applies |
| MCP/hooks/tools | Core composition | Core composition | ohmo adapts around, rather than forks, the engine |
| Permissions/sandbox | Effective OpenHarness settings plus interactive approvals | Same effective runtime settings; remote channels cannot provide the normal TUI approval modal | Persisted gateway `permission_mode`/`sandbox_enabled` are currently inert |
| UI | React terminal, print mode, fallback UI | Same React terminal and backend protocol, or gateway adapters | Different Python backend command/composition |
| Channels | Reusable channel abstractions exist in core | Gateway is the application that composes them into personal-agent workflows | Channel histories are isolated; personal memory is shared |
| Background work | Tasks, agents, swarm, cron, autopilot | Reuses tasks/agents; ohmo cron jobs launch fresh `ohmo --print` processes | Gateway and cron are separate services |

## Memory is several state layers, not one

Before comparing durable memory, distinguish the layers that users often call “memory”:

| Layer | What it contains | What changes it | Does `/compact` change it? |
| --- | --- | --- | --- |
| Engine messages | Current user, assistant, tool-use, and tool-result history | Every conversation turn | Yes; older portions can be replaced |
| Compact boundary/summary | A provider-valid replacement for older engine messages | Manual, proactive, or overflow-triggered compaction | It is the result of compaction |
| Session-memory Markdown | Current goal, next step, verified work, artifacts, and recent-message summaries | Updated after query attempts | Read as one possible compaction checkpoint; not itself erased by `/compact` |
| Session snapshot JSON | Resumable messages, usage, prompt, and safe tool metadata | Saved after handled turns/commands | Later saves contain the compacted message list |
| Durable project/personal memory | Selected facts and preferences meant to survive sessions | Manual commands, extraction where supported, or dream consolidation | No; compaction and durable-memory maintenance are separate |
| Persona files | ohmo soul, identity, user profile, and bootstrap | Explicit file/CLI edits | No |
| Usage index | Recall counts/timestamps for durable entries | Core project-memory prompt selection | No; ohmo personal recall currently does not update it |
| Dream backups | Pre-consolidation copy of durable memory | `/dream run` or automatic dream | No |

The authoritative owners are `src/openharness/engine/query_engine.py`,
`src/openharness/services/compact/__init__.py`,
`src/openharness/services/session_memory/__init__.py`, the injected session backend, and the two
durable-memory adapters.

## Durable memory: what `oh` does

### Storage and scope

Core project memory is derived from the resolved cwd and stored by default under:

```text
~/.openharness/data/memory/<project-name>-<path-hash>/
├── MEMORY.md
├── <topic>.md
├── usage_index.json
└── team/ ...
```

The path hash prevents two repositories with the same basename from sharing memory. `MEMORY.md` is
a bounded index/entrypoint, not the only memory file. Topic entries use schema-v1 YAML frontmatter
with an ID, type, scope, category, importance, signature, timestamps, TTL/disabled fields, and
supersession metadata.

### Recall and prompt evolution

Before each ordinary `oh` prompt, `handle_line()` rebuilds the runtime system prompt. Core memory
recall has two parts:

1. `MEMORY.md` is read with configured line and byte limits.
2. When there is a latest user prompt, `select_relevant_memories()` searches metadata and body
   content, ranks a heuristic shortlist, injects at most `memory.max_files` topic files, and marks
   those entries used best-effort.

This means project-memory context can evolve from one prompt to the next without rebuilding the
runtime. Recall counts and `last_used_at` later help identify low-importance entries that have been
unused for at least 60 days as dream-review candidates. “Stale candidate” is advisory; it is not an
automatic deletion decision.

### Add, update, disable, and migrate

`/memory add` calls `src/openharness/memory/manager.py::add_memory_entry()`:

- a content/type/category signature deduplicates entries;
- identical content refreshes/reactivates the existing file instead of creating a copy;
- title collisions allocate suffixes such as `_2` only when content differs;
- writes hold `.memory.lock` and replace files atomically;
- the entry and `MEMORY.md` are separate atomic writes, so a crash between them can leave an
  unindexed but valid entry.

`/memory remove` is a soft delete: it sets `disabled: true` and removes the index link. It does not
erase the file, old session snapshots, dream backups, or any disclosure already made to a model.

`/memory migrate --dry-run` reports schema normalization. `--apply` creates a migration backup and
rewrites changed top-level entries. `/memory edit` opens the index or selected file through
`$VISUAL`/`$EDITOR`. `/memory validate` checks the project store's type metadata and team-memory
secret rules.

Core also exposes team and agent memory vaults. They are separate scopes under core path helpers;
they are not additional ohmo personal-memory categories.

### Extraction: aggregate a completed turn into durable facts

`/memory extract` and optional `memory.auto_extract_enabled` use a second model request over a
bounded recent transcript and the existing project-memory manifest. The response must parse into at
most `auto_extract_max_records` structured records. Accepted records pass through the normal project
memory manager and its deduplication/team-secret checks.

Extraction is best-effort after the user turn. An extraction failure is stored in tool metadata and
does not turn a completed user request into a failure. It is not conversation compaction: extraction
creates reusable cross-session facts, while compaction changes provider-visible history.

### Dream: reorganize and evolve the store

`/dream preview` or `/dream run` starts a background task through
`src/openharness/services/autodream/service.py`. Automatic dream uses the same workflow when enabled
and its time/session-count gates pass.

The workflow:

1. resolves the project memory and session-snapshot directories;
2. scans snapshots touched since the last successful consolidation;
3. takes a consolidation lock;
4. creates a pre-change backup for apply mode;
5. identifies usage-based stale candidates;
6. launches a separate `python -m openharness --print ...` agent task constrained by prompt policy
   to inspect and modify the memory directory;
7. asks that agent to merge duplicates, correct contradictions, normalize relative dates, mark
   privacy/staleness, disable superseded entries, and keep the index concise; and
8. records changed-file/diff metadata, with `/dream diff` and `/dream rollback` available afterward.

The core dream subprocess is launched with `--dangerously-skip-permissions`. Its “write only inside
the memory directory” rule is model-prompt policy, not a tool-enforced filesystem boundary. The
consolidation prompt is also not transactional proof that every semantic change is correct. Preview
first, run in an appropriately isolated environment, and inspect the diff when memory contains
sensitive or operationally important facts.

## Durable memory: what `ohmo` does differently

### Storage and meaning

ohmo personal memory lives under the selected workspace:

```text
<workspace>/memory/
├── MEMORY.md
└── <entry>.md
```

Default workspaces use `~/.ohmo`, but `--workspace` and `OHMO_WORKSPACE` can select another root.
Entries reuse the core scanner/schema but default to `type: personal` and
`category: preference`. The usual content signature, locking, atomic write, soft delete, and schema
migration behavior are shared with core memory.

The semantic boundary is different: personal memory is for stable user preferences and personal
context across projects/channels. Repository facts should remain in project documentation or core
project memory unless the user deliberately wants them globally personal.

### Recall is bounded, but not relevance-ranked

`ohmo/memory.py::load_memory_prompt()` injects:

- the first 200 lines of personal `MEMORY.md`;
- the first five active entries by sorted scan order by default; and
- at most 4,000 characters from each included file.

Unlike core project memory, this path does not rank entries against the latest prompt, add freshness
labels, or call `mark_memory_used()`. Therefore:

- adding more than five active files can leave later files out of the prompt regardless of topic;
- personal-memory usage counts are not evidence of actual prompt recall; and
- low-importance personal entries older than the stale threshold can appear as dream-review
  candidates even if they were repeatedly included in prompts.

Consolidating related personal facts into a few well-maintained files is therefore more important
for ohmo than for relevance-selected project memory.

### The prompt is captured at runtime construction

Local and gateway composition call `build_ohmo_system_prompt()` when constructing a runtime. That
function reads soul/identity/user/bootstrap and personal memory, then passes the resulting text as
the runtime's custom system-prompt base.

Between turns, core dynamic prompt rebuilding refreshes environment, permission/reasoning state,
skills, project instruction files, local rules, and issue/PR context around that custom base. It
does not call `load_memory_prompt()` for ohmo again. A personal memory changed by `/memory add`, CLI,
or another channel therefore becomes visible when the bundle is refreshed/rebuilt or a new process
starts, not necessarily on the next turn of every already-cached bundle.

Gateway bundles are cached per conversation key, so several channel conversations can temporarily
hold different snapshots of the same shared personal-memory directory.

### Personal commands that are truly rebound

ohmo supplies `MemoryCommandBackend(label="ohmo personal memory", ...)`. These shared `/memory`
operations use the personal directory:

- status/default path display;
- `list`, `show`, `add`, `remove`, and `edit`;
- `migrate --dry-run` and `migrate --apply`;
- `/stats` memory-file count; and
- `/dream` directory/session selection.

The gateway allows ordinary remote-invocable commands only after channel admission. Local-only or
administrator commands still pass through the separate remote-command policy.

### Current memory-boundary exceptions

The backend is not threaded through every shared memory path today:

1. `/memory extract` explicitly rejects any custom memory backend, so it cannot manually extract
   into personal memory.
2. Engine-level automatic extraction does not consult the backend or `autodream_context`; if
   globally enabled during ohmo use, it calls project extraction for the effective cwd and can
   write core project memory.
3. `/memory validate` scans core project memory rather than the personal backend.
4. `/memory session`, `/memory team`, and `/memory agent` use core cwd/config path helpers.
5. Automatic session-memory checkpoints also use the core cwd-hashed data path rather than
   `<workspace>/sessions`.

Consequently, “ohmo excludes project memory” means normal system-prompt project-memory reads are
disabled and common personal `/memory` mutations are rebound. It does not yet prove that every
memory-related command or post-turn writer is workspace-confined. Automatic extraction is off by
default; keep it off for strict ohmo personal/project separation until the adapter boundary is
completed.

### Dream is correctly pointed at the personal store

ohmo local and gateway composition pass `autodream_context` containing personal memory and ohmo
session directories, label, and `runner_module="ohmo"`. `/dream` also resolves those locations from
the injected memory/session backends. A dream task therefore launches `python -m ohmo --print ...`
against the personal store rather than project memory.

The same merge/prune/index policy, locking, preview, diff, and rollback mechanics apply. Unlike the
core runner, the ohmo runner is not automatically passed full-auto permission mode. In default
non-interactive permissions, mutating tools can therefore be denied and an apply dream may complete
without the intended file updates; operators must inspect its output/diff and choose an explicitly
safe effective permission/sandbox policy rather than assuming the prompt grants access.

For the default `~/.ohmo` path, backups go under `~/.ohmo/backups`. A custom workspace whose path
does not contain a `.ohmo` component currently falls back to the core memory-backup root under
OpenHarness data, even though the dream selects the correct custom memory directory.

## Compaction: shared behavior in both applications

Both applications submit messages through `QueryEngine` and `run_query()`. At each provider turn,
the compaction service estimates the request from messages plus the system prompt. The strategy is
ordered from least destructive/expensive to most:

1. **Microcompaction:** replace eligible old tool-result bodies with bounded placeholders while
   preserving tool-use/result pairing.
2. **Context collapse:** trim or collapse stale tool/artifact/context payloads where safe.
3. **Session-memory compaction:** replace older messages with the file-backed session-memory
   checkpoint, or a deterministic summary of older messages when no checkpoint is usable.
4. **Full model compaction:** ask the provider to summarize older history and preserve recent
   messages/checkpoints.

Manual `/compact`, proactive threshold compaction, and one reactive retry after a provider context
overflow share provider-valid message invariants. Compaction emits progress events; the terminal
renders them, while the ohmo gateway converts them to optional localized progress messages.

Three consecutive proactive failures disable further proactive attempts for that run. A context
overflow can still request one forced reactive compaction. Oversized tool results have an earlier
pressure valve: full output is written to a tool artifact and only a bounded reference stays in
history.

The algorithm does not know whether the user is in `oh` or `ohmo`. Differences come from the system
prompt size, session-memory path, session backend, and the adapter that renders progress/saves the
result.

## “Compact,” “reorganize,” “aggregate,” and “evolve” compared

| Operation | `oh` | `ohmo` | What it does not do |
| --- | --- | --- | --- |
| Compact a conversation | `/compact` or automatic shared compactor | Same shared compactor; channel may emit progress | Does not merge durable memory files |
| Update task continuity | Session-memory checkpoint after query attempts | Same core checkpoint logic/path | Is not the resumable session snapshot |
| Add one durable fact | `/memory add` into project store | `/memory add` into personal store | Does not rebuild every cached ohmo bundle immediately |
| Aggregate recent turn facts | `/memory extract` or optional auto-extract | Manual extraction rejected; auto-extract currently targets project cwd | Is not personal-memory extraction today |
| Reorganize schema | `/memory migrate` on project store | Same command on personal store | Does not semantically merge contradictions |
| Reorganize content | `/memory edit`; `/dream preview/run` | Same, targeting personal store | Dream output still requires review |
| Evolve recall | Per-prompt relevance and usage tracking | Fixed bounded snapshot until runtime rebuild | ohmo currently lacks prompt relevance/usage updates |
| Remove obsolete fact | Soft delete or dream sets `disabled` | Same | Does not erase backups/snapshots/provider disclosures |
| Restore after bad consolidation | `/dream rollback` from backup | Same personal-store workflow | Does not roll back sessions or project files |

## Other overlapping concepts

### Scope: workspace is not cwd

For `oh`, the resolved cwd scopes project instructions, project memory, sessions, tools, and many
project services. For `ohmo`, the workspace scopes persona, personal memory, sessions, gateway
configuration, attachments, groups, logs, and workspace extensions; the effective cwd still scopes
tools, project instructions, Git operations, project extensions, and the core path exceptions listed
above.

A managed Feishu group may bind a cwd. That changes tool/project context for its conversation but
does not create a new ohmo workspace or personal-memory store.

### Sessions: execution objects versus resume records

Both applications keep live engine messages in memory and serialize sanitized snapshots through a
`SessionBackend`.

- Core snapshots live under a cwd-hashed OpenHarness session directory.
- Ohmo snapshots live under `<workspace>/sessions`.
- Gateway saves both `session-<id>.json` and `latest-<session-key-hash>.json`, allowing each routed
  conversation to restore its own history.
- The runtime bundle/provider/MCP/hooks/tools are rebuilt; they are never revived from JSON.
- Tool metadata is allowlisted and message sequences are sanitized before persistence.

The top-level React handoff for `--resume`/`--continue` has known gaps in both product launch paths;
in-session restore and gateway keyed restoration have different behavior. See
[memory, sessions, and compaction](flows/MEMORY_SESSION_COMPACTION.md) and
[ohmo session persistence](ohmo/SESSION_PERSISTENCE.md).

### Providers and authentication

Both ultimately call the same provider clients and use core provider profiles/credential stores.
Local ohmo uses the active core profile unless `--profile` overrides it. The gateway persists its
selected profile name in `<workspace>/gateway.json`; `/provider` changes that gateway selection,
while `/model` updates models in the selected core profile. A profile name in gateway state does not
copy credentials into the workspace.

### Tools, permissions, sandbox, and hooks

Both runtimes receive the same built-in/plugin/MCP tool registry, `PermissionChecker`, hook
executor, and optional sandbox from `build_runtime()`. Ohmo gateway adds a narrowly scoped managed
Feishu-group tool only while handling the internal group-creation workflow.

Remote channels do not have the terminal's normal permission modal. Therefore safe remote
operation depends on effective core permission settings, sender/group admission, command remote
authorization, tool rules, sensitive-path denial, and sandbox configuration together. The
`permission_mode` and `sandbox_enabled` fields currently persisted in `gateway.json` are not consumed
by gateway runtime composition; change the effective OpenHarness settings instead.

### Commands

Ohmo reuses the core registry. Local mode uses the same `handle_line()` path; gateway mode performs
remote authorization first and intercepts gateway-scoped `/provider` and `/model`. Attachments make
slash-looking text an ordinary model input rather than a command. `/stop`, `/restart`, and Feishu
`/group` are intercepted even earlier by the bridge.

Do not infer that a shared command name means identical storage ownership. `/memory` demonstrates
why the injected `CommandContext` and individual subcommand implementation must both be traced.

### Skills, plugins, project instructions, and MCP

Ohmo adds `<workspace>/skills` and `<workspace>/plugins` as explicit roots but still composes the
core discovery system for the effective cwd. Project instructions such as `CLAUDE.md` are included;
project memory is a separate switch. Project plugins remain untrusted unless the core
`allow_project_plugins` setting enables them. MCP configuration, hooks, and tool registration are
still core-owned.

### UI and streaming

Both terminal applications use the packaged React/Ink frontend and JSON-lines Python backend. The
backend command decides whether core or ohmo composition is used. Print modes render the same engine
events differently, and the gateway accumulates assistant deltas into one final response while
optionally publishing progress, tool hints, and media earlier.

### Tasks, cron, and long-lived processes

The task manager and model-selected background-agent tools are core services reused by ohmo.
Auto-dream itself is a background task. The ohmo gateway and the core cron scheduler are independent
processes: starting one does not start the other. An ohmo agent-turn cron job launches a fresh
`ohmo --print` process, so it shares durable workspace state but not a cached gateway engine.

### Channels

Core owns channel contracts, adapters, and the in-memory bus. Ohmo owns the production composition:
workspace gateway config, channel manager, admission/routing bridge, per-conversation runtime pool,
workspace snapshots, and channel-specific group commands. Different channels do not share a live
conversation merely because the sender is the same; the channel name is part of every normal
session key. They do share the selected workspace's persona and durable personal-memory files.

See [ohmo channel coordination](ohmo/CHANNEL_COORDINATION_WORKFLOW.md) for the complete ingress,
concurrency, runtime, progress, media, and delivery workflow.

## Practical management recommendations

### For project knowledge in `oh`

1. Keep `MEMORY.md` as a concise index.
2. Use topic files with stable facts; let relevance select among them.
3. Use `/memory extract` only when the recent turn contains genuinely durable knowledge.
4. Run `/memory migrate --dry-run` before applying schema normalization.
5. Use `/dream preview`, inspect, then run/apply and review `/dream diff`.
6. Treat soft-deleted files and backups as retained data during privacy cleanup.

### For personal knowledge in `ohmo`

1. Keep no more than a few coherent active files when possible because recall is first-five, not
   query-ranked.
2. Put personality/behavior in soul or user-profile files; put reusable facts/preferences in
   personal memory; keep repository truth in the repository/project store.
3. Restart or refresh long-lived local/gateway bundles after important memory edits.
4. Leave global auto-extraction off when strict personal/project isolation matters.
5. Preview and review personal dreams; remember that custom-workspace backups may live in the core
   backup root.
6. Back up the whole workspace when persona, sessions, gateway config, groups, attachments, and
   memories must move together.

## Current limitations that should guide maintenance

- `include_project_memory=False` is a read-path control, not a universal storage sandbox.
- ohmo personal-memory mutations do not immediately refresh every cached runtime prompt.
- ohmo personal recall has no query relevance or usage accounting.
- automatic extraction is core-project-specific even inside an ohmo engine.
- some shared `/memory` subcommands bypass the injected memory backend.
- session-memory checkpoints are core cwd/config data for both products.
- core dream path isolation is prompt-only, while ohmo dream mutation permissions are not forced.
- gateway runtime bundles have no inactivity eviction or pool-wide shutdown close.
- the in-memory channel bus has no durable queue or configured bound.

These are current-state facts, not recommended extension patterns. The corresponding remediation is
tracked in the [improvement backlog](IMPROVEMENTS.md).

## Evidence map

| Claim area | Primary source | Focused tests/reference |
| --- | --- | --- |
| Runtime composition | `src/openharness/ui/runtime.py::build_runtime()` | `tests/test_ui/`, `tests/test_ohmo/test_loading.py` |
| Project prompt memory | `src/openharness/prompts/context.py::build_runtime_system_prompt()` | `tests/test_memory/` |
| Project memory mutation | `src/openharness/memory/manager.py` | `tests/test_memory/test_claude_runtime_memory.py` |
| Personal prompt/mutation | `ohmo/memory.py`, `ohmo/prompts.py` | `tests/test_ohmo/test_prompts.py` |
| Session memory | `src/openharness/services/session_memory/__init__.py` | `tests/test_memory/test_claude_runtime_memory.py`, `tests/test_services/test_compact.py` |
| Extraction | `src/openharness/services/memory_extract/__init__.py`, `src/openharness/engine/query_engine.py::_extract_durable_memories()` | `tests/test_memory/test_claude_runtime_memory.py`, `tests/test_engine/test_query_engine.py` |
| Consolidation | `src/openharness/services/autodream/` | `tests/test_services/test_autodream.py` |
| Compaction | `src/openharness/services/compact/__init__.py` | `tests/test_services/test_compact.py`, `tests/test_engine/test_query_engine.py` |
| Session backends | `src/openharness/services/session_backend.py`, `ohmo/session_storage.py` | `tests/test_services/test_session_storage.py`, `tests/test_ohmo/test_ohmo_session_storage.py` |
| Gateway runtime/prompt refresh | `ohmo/gateway/runtime.py` | `tests/test_ohmo/test_gateway.py` |
| Channel coordination | `src/openharness/channels/`, `ohmo/gateway/` | `tests/test_channels/`, `tests/test_ohmo/test_gateway.py` |
