# `oh` user guide: common scenarios and workflows

`oh` is the core OpenHarness coding-agent command. It can inspect and change a working directory,
run tools under a permission policy, retain project-scoped conversations and memory, load skills and
plugins, connect MCP servers, coordinate background work, and run one prompt for a script.

This is a user guide for the behavior implemented in the current repository. For implementation
details, see [how the `oh` command reaches the runtime](../developer/flows/CLI_ENTRYPOINTS.md), the
[interactive frontend/backend flow](../developer/flows/INTERACTIVE_OH_FRONTEND_BACKEND_E2E.md),
and the [architecture overview](../ARCHITECTURE.md).

## Command convention

Examples use the installed command:

```bash
oh --help
```

When working from a source checkout, prefix commands with `uv run`:

```bash
uv run oh --help
```

`openharness`, `oh`, and `openh` are aliases for the same application. On Windows PowerShell, use
`openh` because `oh` can resolve to the built-in `Out-Host` alias.

Unless an example says otherwise, run it from the repository or directory that the agent should be
allowed to inspect. The current working directory scopes project instructions, sessions, memory,
skills, plugins, Git operations, and most tool activity.

## Choose the workflow you need

| Scenario | Start here | Persistent state involved |
| --- | --- | --- |
| First-time setup | `oh setup` | Provider settings and authentication |
| Check configuration without calling a model | `oh --dry-run` | Reads settings; does not run tools |
| Work interactively in a repository | `cd /path/to/repo && oh` | Project session and memory state |
| Ask for analysis without changes | `/permissions plan` | Persisted permission mode |
| Run one prompt for a script | `oh -p "..."` | A project session snapshot |
| Resume a conversation | Start `oh`, then use `/resume` | Project-scoped session snapshots |
| Teach reusable project facts | `/memory add TITLE :: CONTENT` | Project-scoped durable memory |
| Add reusable instructions | Create a project or user skill | Skill directories |
| Connect an external tool server | `oh mcp add ...` | MCP settings |
| Run a shell task in the background | `/tasks run COMMAND` | Task records and output |
| Repeat work on a schedule | Ask `oh` to create a command cron job, then `oh cron start` | Shared cron registry and logs |
| Queue autonomous repository work | `oh autopilot ...` | `.openharness/autopilot` in that repository |
| Diagnose a problem | `/doctor`, `oh auth status`, `oh --dry-run` | Configuration and local diagnostics |
| Back up or migrate | Copy the relevant configuration, data, and project state securely | Credentials, sessions, memory, extensions |

## 1. Install and configure a provider

Install the published package:

```bash
pip install openharness-ai
```

Or follow the installation options in the project [README](../../README.md#quick-start). From a
source checkout, install development dependencies with:

```bash
uv sync --extra dev
```

Run the setup wizard and select a provider workflow:

```bash
oh setup
```

You can also configure a named built-in profile directly:

```bash
oh setup codex
oh setup claude-subscription
```

The available profile names depend on the installed version. Inspect the current state instead of
guessing:

```bash
oh provider list
oh auth status
```

Provider status proves that configuration or a credential source was found; it is not a live model
request. Verify the selected profile with a small prompt:

```bash
oh -p "Reply with exactly: OK" --max-turns 1
```

For a local LM Studio server using its Anthropic-compatible API, follow the dedicated
[LM Studio guide](../providers/LM_STUDIO_ANTHROPIC.md). For example, its provider profile is created
under `~/.openharness/settings.json`, while the supplied API key is stored through the OpenHarness
credential backend rather than written into the profile itself.

Prefer the interactive `oh setup` or `oh auth login` flow over passing secrets on a command line.
Both the root `--api-key` option and `oh provider add ... --api-key ...` can expose a value through
shell history or process inspection, even though the latter persists it through the credential
backend. If no usable system keyring is available, OpenHarness stores credentials as plaintext JSON
in `~/.openharness/credentials.json`, protected by file permissions rather than encryption.

## 2. Select and initialize the working directory

The simplest way to choose the project is to enter it before starting `oh`:

```bash
cd /path/to/repository
oh
```

There is also a hidden `--cwd` runtime option, used internally and by automation, but changing
directory first makes shell commands, Git state, and project discovery easier to reason about.

Inside the TUI, initialize basic project files with:

```text
/init
```

This creates missing files only:

- `CLAUDE.md`
- `.openharness/README.md`
- `.openharness/memory/MEMORY.md`
- `.openharness/plugins/.gitkeep`
- `.openharness/skills/.gitkeep`

Review every generated file before committing it. `CLAUDE.md` is loaded as project instruction
context. The prompt loader also discovers `.claude/CLAUDE.md` and `.claude/rules/*.md` from the
current directory upward. In this release, the core prompt loader does **not** discover
`AGENTS.md` automatically.

The `.openharness/memory/MEMORY.md` seed created by `/init` is not the active durable-memory store
used by the runtime. Use `/memory` to display the authoritative project memory directory, which is
under `~/.openharness/data/memory/<project>-<hash>/` by default. Treat the seeded project file as a
placeholder unless your own instructions or extension consume it.

Useful first requests are:

- “Inspect this repository and explain its architecture before changing anything.”
- “Diagnose the failing test, but do not implement a fix.”
- “Implement this issue, run focused tests, and show me the diff.”
- “Review the uncommitted changes for correctness and security.”

State authority explicitly. A request to diagnose or review does not imply permission to edit;
request “fix” or “implement” when changes are wanted. Request commits, pushes, releases, messages,
or other external side effects separately.

## 3. Work in the interactive terminal

Start the terminal UI:

```bash
oh
```

The installed `oh` console script enters Python first. Normal interactive mode then starts the
React/Ink frontend from `frontend/terminal/src/index.tsx`; that frontend starts a second Python
process with `--backend-only`, and the second process owns the model runtime. This is expected, not
a duplicate session.

Common controls are:

| Input | Behavior |
| --- | --- |
| `Enter` | Submit the prompt |
| `Shift+Enter` | Insert a newline |
| `/` | Start or discover a slash command |
| `Tab` on empty input | Open the permission-mode picker |
| Up/Down | Navigate prompt history or a picker |
| `Escape` or `Ctrl+C` while busy | Interrupt the active turn |
| `Ctrl+C` while idle | Exit |
| `Ctrl+V` | Attach an image from the clipboard when the platform helper can read one |
| Double `Escape` | Clear current input and attachments |

Clipboard image support uses native helpers. Linux generally needs `wl-paste`, `xclip`, or `xsel`;
macOS and Windows use their platform clipboard facilities. Image understanding still depends on
the selected model or configured vision fallback.

Useful slash commands include:

| Command | Purpose |
| --- | --- |
| `/help` | List commands and project-contributed slash commands |
| `/status` | Show model, cwd, permissions, and runtime status |
| `/context` | Show the assembled system prompt |
| `/files [FILTER]` | List project files |
| `/branch`, `/diff` | Inspect Git state |
| `/permissions` | Show or change permission mode |
| `/provider`, `/model` | Inspect or change the active provider/model |
| `/skills` | List or inspect skills |
| `/hooks` | Show configured hooks |
| `/mcp` | Show MCP runtime status |
| `/memory` | Inspect or manage durable project memory |
| `/compact` | Compact older conversation history |
| `/cost`, `/usage`, `/stats` | Inspect token, cost, or session information |
| `/session` | Show session storage information |
| `/resume` | List saved sessions; `/resume ID` restores one |
| `/export` | Export the current transcript as Markdown |
| `/tag NAME` | Create a named session snapshot |
| `/rewind [COUNT]` | Remove recent conversation turns |
| `/tasks` | Inspect or manage background tasks |
| `/agents` | Inspect delegated worker tasks |
| `/stop` | Interrupt an active turn |
| `/exit` | Exit OpenHarness |

Run `/help` in your current session for the authoritative list. Enabled plugins and user-invocable
skills may add commands.

## 4. Control permissions and sandboxing

Permissions decide whether a model-requested tool may execute. The three modes are:

| Mode | Read-only tools | Mutating tools |
| --- | --- | --- |
| `default` | Allowed | Ask for confirmation |
| `plan` | Allowed | Blocked |
| `full_auto` | Allowed | Allowed without confirmation |

Set a mode from the TUI:

```text
/permissions plan
/permissions default
/permissions full_auto
```

The selection is saved in OpenHarness settings and therefore affects later sessions, not only the
current prompt. Press `Tab` on empty input to open the same picker. For edit/write previews in
default mode, `y` approves once, `a` approves edits for the rest of the session, and `n` rejects.

`full_auto` is not a substitute for isolation. OpenHarness still denies built-in sensitive paths
such as SSH keys, cloud credentials, Docker/Kubernetes credentials, and its own credential files;
explicit deny rules also remain effective. It can nevertheless modify ordinary files and execute
commands, so use it only in a controlled working directory.

The `--dangerously-skip-permissions` root option currently selects `full_auto`; it does not remove
the built-in sensitive-path checks despite its help text. Avoid it unless you have separately
isolated the environment.

### Enable a command sandbox

Sandboxing is disabled by default. The default backend is Anthropic's sandbox runtime (`srt`), and
Docker is available as an alternative. A conservative `srt` configuration is:

```bash
oh config set sandbox.enabled true
oh config set sandbox.backend srt
oh config set sandbox.fail_if_unavailable true
```

Install `@anthropic-ai/sandbox-runtime` separately. Linux/WSL also needs `bwrap`; macOS needs
`sandbox-exec`. Native Windows does not support the `srt` backend, so use WSL or Docker.

For Docker:

```bash
oh config set sandbox.enabled true
oh config set sandbox.backend docker
oh config set sandbox.fail_if_unavailable true
```

Inspect the effective settings and environment diagnostics:

```bash
oh config show
```

Then run `/doctor` inside the TUI. If sandboxing is enabled but unavailable while
`sandbox.fail_if_unavailable` is false, supported commands fall back to the host. Set it to true
when an unsandboxed fallback would be unacceptable.

Permissions and sandboxing are different layers: permission mode decides whether a tool is
authorized; the sandbox decides where a supported process executes.

## 5. Preview runtime configuration safely

Dry-run mode resolves the runtime metadata without calling the model, executing tools, connecting
MCP servers, or spawning subagents:

```bash
oh --dry-run
oh --dry-run -p "Fix the failing tests"
oh --dry-run -p "/memory list" --output-format json
```

The preview reports the selected provider/model, authentication readiness, permission mode,
prompt sources, skills, commands, tools, configured MCP servers, and suggested next actions. Prompt
previews also identify likely relevant skills and tools.

`--output-format stream-json` emits one compact JSON preview line in dry-run mode; it is not a live
event stream. Dry-run does not currently accept `--continue` or `--resume`.

Dry-run is a static readiness check. It cannot prove that a credential is valid, an endpoint is
reachable, an MCP server starts, or a model supports tool use.

## 6. Run one prompt and exit

Print mode uses the same model/tool loop without opening the TUI:

```bash
oh -p "Summarize this repository"
oh -p "Find the likely cause of the failing tests" --max-turns 6
oh -p "Explain src/openharness/cli.py" --model MODEL_ID
```

In text mode, assistant text goes to stdout and status/error notices go to stderr. This makes basic
piping possible:

```bash
oh -p "Write a short architecture summary" > architecture-summary.txt
```

For automation, choose a structured format:

```bash
oh -p "List the main packages" --output-format json
oh -p "Run the focused tests and summarize" --output-format stream-json
```

`json` emits one final object shaped like:

```json
{"type":"result","text":"..."}
```

`stream-json` emits newline-delimited events such as `assistant_delta`, `tool_started`,
`tool_completed`, `status`, `error`, and `assistant_complete`. Consumers should parse each line as
an independent JSON object rather than treating the stream as one array.

### Important print-mode permission behavior

Print mode cannot display an approval dialog. In the current implementation, confirmation-required
mutations in persisted `default` mode are automatically approved. In addition, the root
`--permission-mode` and `--dangerously-skip-permissions` values are not forwarded into the print
runtime, so they do not reliably change one-shot policy. Persisted `plan` mode still blocks
mutations, and explicit deny rules and sensitive-path protection still apply.

For unattended read-only use, first persist plan mode from an interactive session:

```text
/permissions plan
```

Then exit and run the one-shot request. Restore `/permissions default` in a later interactive
session when you want confirmation-based edits again. For any job that may mutate files, prefer an
interactive run or isolate and review the working directory before using print mode.

Do not rely only on the process exit code to classify every model/runtime error; parse structured
error events or validate the requested output and resulting state.

## 7. Save, resume, and export conversations

OpenHarness saves snapshots under:

```text
~/.openharness/data/sessions/<project-name>-<12-character-path-hash>/
```

The path hash keeps repositories with the same directory name separate. Typical files include
`latest.json`, `session-<id>.json`, and `transcript.md`. Session files can contain prompts, model
responses, tool inputs/results, local paths, and usage metadata.

Use the in-TUI workflow:

```text
/session
/resume
/resume SESSION_ID
/tag before-refactor
/export
```

`/resume` without an ID lists recent snapshots for the current working directory. Restoring a
snapshot replaces the active engine message history and replays it in the TUI.

The top-level `oh --continue` and `oh --resume` options currently load snapshot data in the first
Python process but do not pass it through the normal React launcher to the second backend process.
Use `/resume` inside an already-started TUI until that frontend handoff is fixed.

Sessions are project-scoped. Starting `oh` in another path creates or reads a different session
directory even when the model and provider are unchanged.

## 8. Change providers, models, and settings

Inspect and activate provider profiles:

```bash
oh provider list
oh provider use PROFILE_NAME
oh auth status
```

Inside a session, use:

```text
/provider list
/provider use PROFILE_NAME
/model show
/model list
/model MODEL_ID
```

Changing a profile or model in the TUI refreshes the runtime state; follow the command's restart
message if one is shown. A model name alone does not prove API compatibility: the profile's
provider, API format, base URL, authentication source, and model all participate in client
selection.

Inspect resolved settings with secrets redacted:

```bash
oh config show
```

Set a supported top-level or dotted nested value with:

```bash
oh config set max_turns 100
oh config set effort high
oh config set sandbox.enabled true
```

The default settings file is `~/.openharness/settings.json`. Override storage roots for a test or
isolated environment:

```bash
export OPENHARNESS_CONFIG_DIR=/path/to/config
export OPENHARNESS_DATA_DIR=/path/to/data
export OPENHARNESS_LOGS_DIR=/path/to/logs
```

These variables must be set consistently for commands that should share state. Other provider and
runtime environment variables exist, including `OPENHARNESS_MODEL`, `OPENHARNESS_BASE_URL`,
`OPENHARNESS_API_FORMAT`, and provider-specific API-key variables. Explicit CLI overrides generally
take precedence for the fields that are wired through.

`--theme NAME` saves the selected theme to settings; it is not only a one-run override. You can
also manage themes with `/theme`.

## 9. Store durable project memory

Conversation history and durable memory are different. Sessions retain a transcript; project
memory stores selected facts intended to survive across sessions and be retrieved into future
prompts.

Inspect the active store:

```text
/memory
/memory list
```

Add and inspect an entry:

```text
/memory add Build command :: Run uv run pytest -q tests/test_engine for engine changes.
/memory list
/memory show build-command.md
```

Remove an entry:

```text
/memory remove build-command.md
```

Removal soft-disables the entry so it is no longer selected; the underlying file may remain for
audit or recovery. `/memory` prints the authoritative directory and `MEMORY.md` entrypoint. By
default it is:

```text
~/.openharness/data/memory/<project-name>-<12-character-path-hash>/
```

Memory commands also support validation, explicit extraction from the current turn, migration,
and advanced session/team/agent scopes. Run `/memory` for the current syntax before using those
operations.

`/dream preview` or `/dream run` starts a background consolidation pass with backup metadata.
Inspect it through `/tasks` and `/dream diff latest`; keep `/dream rollback latest` available until
you have reviewed the result. Consolidation may make a model request and rewrite memory files, so
it is not a read-only maintenance command.

Do not store credentials or private keys in project memory. Memory text may be injected into model
prompts and is stored locally as readable Markdown.

## 10. Add skills, plugins, hooks, and MCP servers

### Skills

A skill is a directory containing `SKILL.md`. User skills are loaded from:

- `~/.openharness/skills`
- `~/.claude/skills`
- `~/.agents/skills`

Project skills are discovered from the current directory up to the Git root in:

- `.openharness/skills`
- `.agents/skills`
- `.claude/skills`

Project skills are enabled by default. More-specific definitions override broader definitions with
the same name. Inspect discovery with `/skills` or `oh --dry-run`. A skill marked user-invocable may
also appear as its own slash command.

### Plugins

User plugins are installed under `~/.openharness/plugins`:

```bash
oh plugin install /absolute/path/to/plugin-directory
oh plugin list
```

The current installer copies a local directory. Although some help text mentions a URL, URL fetch
and installation are not implemented; clone or download the plugin yourself, inspect it, and pass
its local path.

Project plugins live in `.openharness/plugins` and are untrusted code. They are disabled unless
`allow_project_plugins` is explicitly set to true:

```bash
oh config set allow_project_plugins true
```

Only enable that setting after reviewing the workspace. Plugins can contribute Python tools,
hooks, commands, skills, agents, and MCP servers, so opening an untrusted project with project
plugins enabled can execute code during discovery or tool use. Restart the session after plugin
changes unless the command explicitly reloads them.

### Hooks

Hooks run at configured lifecycle or tool events. Use `/hooks` to inspect the active definitions.
Pre-tool hooks can block an invocation; post-tool hooks observe results. Hook configuration is
advanced and is documented in [Extending OpenHarness](../EXTENDING.md).

### MCP servers

Persist an MCP server as JSON:

```bash
oh mcp add local-files '{"type":"stdio","command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","/path/to/allowed/root"]}'
oh config show
```

Remove it with:

```bash
oh mcp remove local-files
```

The current `oh mcp list` implementation crashes after typed MCP settings are loaded, so use the
redacted `oh config show` output to inspect saved configuration. That still does not prove that the
process starts or a network endpoint is reachable. Start a new TUI and use `/mcp` to inspect runtime
connection status. Restart after changing MCP configuration or completing an MCP authentication
flow.

The top-level `--mcp-config` option is currently declared but not consumed by runtime construction.
Use `oh mcp add` or plugin-provided MCP configuration instead.

## 11. Run background tasks and delegate work

Start a shell command without blocking the prompt:

```text
/tasks run uv run pytest -q tests/test_engine
```

Inspect and control it:

```text
/tasks
/tasks show TASK_ID
/tasks output TASK_ID
/tasks stop TASK_ID
```

Background tasks continue in a local child process only while the surrounding runtime and process
environment support them. Their output and metadata may be stored under
`~/.openharness/data/tasks`.

For model-backed delegation, ask the assistant to use the `agent` tool. Then inspect workers with:

```text
/agents
/agents show TASK_ID
```

Delegated workers have separate contexts and may run concurrently. Review their output and Git
state before accepting changes. Non-interactive workers auto-approve confirmation callbacks after
the configured permission policy evaluates the tool; persisted plan mode and explicit denial rules
still provide important limits.

## 12. Repeat work with the cron scheduler

OpenHarness includes a local cron registry and daemon. There is no `oh cron add` subcommand; cron
jobs are created by the model-callable `cron_create` tool or by another subsystem such as
autopilot.

For a direct shell job, ask interactively:

> Create a cron job named repo-status with schedule `0 */8 * * *`, in this repository, that runs
> `oh -p "Inspect Git status and write a concise report" --max-turns 4`. Do not start the daemon.

Review the proposed tool call before approving it, then operate the scheduler:

```bash
oh cron list
oh cron start
oh cron status
oh cron history repo-status
oh cron logs
```

Pause or remove jobs through the TUI tools, or toggle one from the shell:

```bash
oh cron toggle repo-status false
oh cron toggle repo-status true
```

Cron state is shared across OpenHarness and ohmo at
`~/.openharness/data/cron_jobs.json`. The detached daemon records history under the data directory
and logs under `~/.openharness/logs`. It does not install itself as an operating-system login or
boot service; the machine must be awake and the daemon must be running. Each job has a five-minute
execution timeout.

An important boundary: a cron job created with an `agent_turn` message payload currently launches
`ohmo --print`, not `oh`, and may use ohmo gateway profile/delivery settings. For a recurring core
`oh` workflow, create an explicit shell `command` job that invokes `oh -p ...`. Remember the
print-mode permission behavior described earlier, and ensure the detached process has the necessary
PATH, provider credentials, environment variables, and working directory.

Stopping the scheduler pauses every registered cron job, including ohmo and autopilot jobs:

```bash
oh cron stop
```

## 13. Use repository autopilot carefully

Autopilot maintains a repository-local queue, intake scans, policies, journals, isolated worktrees,
run artifacts, verification, and optional pull-request handling.

Initialize and inspect the queue, or add work without executing a queued card:

```bash
oh autopilot status --cwd /path/to/repo
oh autopilot list --cwd /path/to/repo
oh autopilot add manual_idea "Improve error reporting" --body "Keep behavior compatible" --cwd /path/to/repo
oh autopilot context --cwd /path/to/repo
```

These commands are not filesystem-read-only. Constructing the repository store creates missing
policy, registry, context, run, and dashboard files under `.openharness/autopilot/` and
`docs/autopilot/`. Review the resulting Git diff before committing anything.

Scan supported intake sources:

```bash
oh autopilot scan issues --cwd /path/to/repo
oh autopilot scan prs --cwd /path/to/repo
oh autopilot scan all --cwd /path/to/repo
```

GitHub scans and pull-request operations require `gh`, authentication, network access, and a valid
Git repository. Running a queued card can edit files, create a worktree/branch, run verification,
push, open or update a pull request, and possibly merge when policy allows:

```bash
oh autopilot run-next --cwd /path/to/repo
```

Review `.openharness/autopilot/autopilot_policy.yaml`, `verification_policy.yaml`, and
`release_policy.yaml` before the first run. Current default execution uses `full_auto`, a separate
Git worktree, `main` as the base branch, 12 turns, and up to three attempts. The default decision
policy has a human gate, and automatic merging is label-gated by `autopilot:merge`, but those gates
do not make the execution phase read-only.

Install recurring scan and tick jobs only after reviewing those policies:

```bash
oh autopilot install-cron --cwd /path/to/repo
oh cron list
oh cron start
```

This creates `autopilot.scan` every 30 minutes and `autopilot.tick` every two hours in the shared
cron registry. Autopilot state lives in `.openharness/autopilot/`; dashboard export defaults to
`docs/autopilot/` and may create generated repository files.

## 14. Back up, migrate, or reset state

The default local state map is:

| State | Default location | Notes |
| --- | --- | --- |
| Settings and provider profiles | `~/.openharness/settings.json` | May contain endpoint/profile metadata |
| API credentials | System keyring or `~/.openharness/credentials.json` | File fallback is plaintext with restrictive mode |
| Subscription bindings/tokens | OpenHarness and external CLI auth stores | Location depends on auth workflow |
| Sessions | `~/.openharness/data/sessions/<project>-<hash>/` | Prompts, responses, tool data, usage |
| Durable project memory | `~/.openharness/data/memory/<project>-<hash>/` | Readable Markdown and metadata |
| User skills | `~/.openharness/skills/` | Executable instructions/resources may be referenced |
| User plugins | `~/.openharness/plugins/` | Trusted local code |
| Tasks and cron | `~/.openharness/data/tasks/`, `cron_jobs.json` | Process metadata, commands, output/history |
| Logs | `~/.openharness/logs/` | May contain paths, errors, and tool/provider details |
| Project extensions | `.openharness/`, `.agents/`, `.claude/` | Review before committing |
| Autopilot state | `<repo>/.openharness/autopilot/` | Queue, policies, journals, and run reports |

Stop interactive sessions, cron, and other workers before taking a consistent backup:

```bash
oh cron stop
```

Back up only the state you need, using encryption and restrictive filesystem permissions. Session,
memory, task, and log files may contain source snippets, private prompts, tool output, absolute
paths, and model responses. Never commit personal `~/.openharness` state or credentials.

API credentials may be in a system keyring, provider environment variable, Codex/Claude external
credential store, or OpenHarness file store. Copying `~/.openharness` is therefore neither a
universal authentication backup nor proof that credentials were removed elsewhere.

To test with clean state without deleting anything, point all three storage roots to empty
directories:

```bash
export OPENHARNESS_CONFIG_DIR=/tmp/openharness-test/config
export OPENHARNESS_DATA_DIR=/tmp/openharness-test/data
export OPENHARNESS_LOGS_DIR=/tmp/openharness-test/logs
oh --dry-run
```

Rename existing state rather than deleting it until you have verified the replacement and reviewed
the backup for secrets.

## 15. Troubleshooting

### `oh` cannot call a model

```bash
oh auth status
oh provider list
oh --dry-run -p "Reply with OK"
oh -p "Reply with OK" --max-turns 1
```

Dry-run localizes missing auth/configuration without spending a model call. A successful dry-run
does not prove endpoint reachability. Confirm the active profile's API format, base URL, model, and
credential source together.

### The terminal frontend does not start

From a source checkout, install its dependencies and type-check it:

```bash
cd frontend/terminal
npm ci
npx tsc --noEmit
```

The Python launcher also attempts `npm install` when `node_modules` is absent. Confirm that Node.js
and npm are on PATH. Use `oh --debug` for additional Python-side logs.

### A tool changed files without asking in print mode

This is the current non-interactive approval behavior described in section 6. Inspect the Git diff,
restore only the changes you do not want, and persist `/permissions plan` before another unattended
read-only run. Do not assume `--permission-mode plan` changes print mode in this release.

### A session did not resume

Start `oh` in the same project path and use:

```text
/resume
/resume SESSION_ID
```

Do not use the top-level `--continue`/`--resume` path with the normal React frontend in this release.
If no sessions appear, check the exact working directory and the matching hashed directory under
`~/.openharness/data/sessions`.

### Project instructions or skills are missing

Run `/context`, `/skills`, or `oh --dry-run`. Confirm that instruction filenames and skill roots
match the supported paths, that the process started in the expected directory, and that a Git root
did not stop project-skill traversal earlier than expected. `AGENTS.md` is not part of core prompt
discovery.

### A plugin does not load

Use a local plugin directory containing a valid `plugin.json` or `.claude-plugin/plugin.json`.
Check `oh plugin list` and `/plugin list`. Project plugins require `allow_project_plugins=true`, and
changes generally require a restart. Do not pass a URL directly to the current installer.

### An MCP server does not connect

1. Inspect the saved JSON with `oh config show`; `oh mcp list` is currently broken for typed MCP
   configuration.
2. Start a fresh TUI and run `/mcp`.
3. Confirm the executable, arguments, cwd, and environment are available to the `oh` process.
4. For HTTP/WebSocket transports, verify the endpoint and authentication outside OpenHarness.
5. Restart after configuration or auth changes.

### A scheduled job did not run

```bash
oh cron status
oh cron list
oh cron logs
oh cron history JOB_NAME
```

Confirm the daemon is running, the job is enabled, the cron expression/timezone is correct, its cwd
exists, the machine was awake, and required commands and credentials are available to the detached
process. Check whether the job is a direct command or an `agent_turn` payload that launches `ohmo`.

### The sandbox did not isolate a command

Inspect `sandbox.enabled`, `sandbox.backend`, and `sandbox.fail_if_unavailable` in
`oh config show`. Confirm the selected backend and platform dependency are installed. Set
`fail_if_unavailable=true` when falling back to the host is not acceptable.

## Current behavior to keep in mind

- `oh` is a local process, not a hosted service. Background and scheduled work depends on local
  processes, credentials, PATH, filesystem access, and machine availability.
- Normal interactive `oh` is a Python launcher, a React/Ink terminal process, and a second Python
  backend runtime.
- Project scope is derived from the exact working-directory path; sessions and durable memory use
  separate path-hashed stores under `~/.openharness/data`.
- `CLAUDE.md`, `.claude/CLAUDE.md`, and `.claude/rules/*.md` are prompt inputs; `AGENTS.md` is not
  discovered by the core loader in this release.
- `/init` creates `.openharness/memory/MEMORY.md`, but core durable memory lives in the hashed user
  data directory reported by `/memory`.
- Use in-TUI `/resume`; top-level `--continue` and `--resume` do not transfer restored messages
  through the normal React launcher.
- Print mode auto-approves default-mode confirmation requests and currently ignores its
  per-invocation permission override. Persist plan mode or isolate the workspace for unattended
  read-only work.
- The root `--name`, `--verbose`, `--settings`, `--bare`, `--allowed-tools`, `--disallowed-tools`,
  and `--mcp-config` options are declared in help but are not wired into the selected runtime path.
- `--append-system-prompt` is reflected in dry-run previews but is not forwarded to either the
  print runtime or the interactive React/backend runtime.
- `--theme` persists settings. Root `--api-key` can expose secrets through process arguments.
- `oh mcp list` currently assumes dictionary values after settings have converted them to typed MCP
  models and raises an attribute error; use `oh config show` plus in-session `/mcp` instead.
- User plugins are trusted local code; project plugins are disabled by default. The current plugin
  installer accepts a local directory, not a URL.
- Cron `agent_turn` payloads launch `ohmo`; recurring core workflows should use an explicit command
  job invoking `oh`.
- Autopilot defaults to full-auto execution in an isolated worktree. Review all three policy files,
  queued work, repository status, and external-service permissions before running it. Even status
  and inspection commands initialize repository-local autopilot and dashboard files.
