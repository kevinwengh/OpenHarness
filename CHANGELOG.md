# Changelog

All notable changes to OpenHarness should be recorded in this file.

The format is based on Keep a Changelog, and this project currently tracks changes in a lightweight, repository-oriented way.

## [Unreleased]

### Fixed

- Preserved pre-tool/carryover/post-tool hook ordering after extracting reusable tool governance,
  kept legacy gateway control commands ahead of automation dispatch, retained manual-memory append
  semantics, isolated automation prompts from ambient personal/project context, and made targeted
  automation commands avoid resuming unrelated runs.
- Hardened automation persistence and policy boundaries with event credential redaction, explicit
  approval-destination validation, governed installed-tool execution, bounded unique event
  ancestry, isolated sandbox ownership, and gateway startup cleanup.

### Added

- The first local `oh web` increment: a loopback-only aiohttp host with launch-token and origin
  enforcement, credential-redacted bootstrap status, CSP/security headers, deterministic cleanup,
  packaged React/Vite assets, and a responsive accessible shell covering every planned main area.
- An interactive local-web workbench using the shared terminal runtime controller, including
  streamed transcript and tools, bounded images, interrupt, fail-closed permission/edit/question
  dialogs, one-tab reconnect semantics, session resume/new-session flows, and live provider, model,
  permission, effort, turn, fast-mode, pass, and output-style selectors.
- Searchable local-web screens and bounded resource APIs for Capabilities, Work, Knowledge, and
  Autopilot, plus confirmed operations through a strict same-origin action allowlist for stopping
  tasks/bridges, toggling or running cron jobs, and enqueueing manual Autopilot ideas through their
  existing subsystem owners.
- A keyboard-accessible local-web command palette, bounded recent-session browser, safe GFM
  rendering for completed assistant output and plans, automated accessibility checks, and a clean
  full frontend dependency audit after updating the Vite/Vitest toolchain.
- Declarative Ohmo automation workflows with safe YAML rules, deterministic channel-event
  matching, durable/idempotent runs, restricted named-skill agent steps, conditional multi-step
  actions, cross-channel delivery, namespaced personal-knowledge upserts, crash recovery, and
  trusted plugin automation actions, plus durable actor-authorized approvals and local validation,
  dry-run, submission, inspection, retry, cancellation, and approval commands. Workflow-wide
  duration, retained-history, plaintext-credential, and structured audit-log bounds are enforced.
- A source-level `oh` versus `ohmo` concept comparison covering memory recall and evolution,
  compaction, sessions, providers, tools, permissions, extensions, UI, tasks, current isolation
  gaps, and a complete multi-channel gateway coordination workflow.
- A detailed VS Code development/debugging and local source-release workflow, including
  non-overwriting editor templates, isolated validation state, inspected/checksummed artifacts,
  versioned installations, dedicated launchers, activation, and executable rollback.
- Security, operations, compatibility, release, configuration/state/capability references,
  repository-autopilot and bridge deep dives, accepted ADRs, and GitHub-renderable SVG diagrams,
  with an automated documentation-integrity check.
- A comprehensive autopilot-dashboard reference covering snapshot generation, React rendering,
  scheduled refresh, GitHub Pages publication, privacy boundaries, and current freshness/build gaps.
- Deep function-level developer references and GitHub-renderable call-sequence diagrams across the
  complete critical-flow suite, including CLI dispatch, runtime composition, prompts/tools,
  governance, memory, MCP, extensions, terminal IPC, ohmo, and background agents.
- A comprehensive `oh` user guide covering setup, project scope, the terminal UI, permissions and
  sandboxing, dry-run and print workflows, sessions, memory, extensions, background and scheduled
  work, autopilot, state management, troubleshooting, and current CLI limitations.
- Dedicated end-to-end developer guides for the interactive `uv run oh` Python/React process flow and for prompt ingestion, memory selection, tool-result replay, context compaction, and session persistence.
- A layered local LM Studio manual-test runbook covering provider setup, dry-run inspection, headless `oh`, the React terminal frontend/backend, `ohmo` workspace and memory behavior, and optional channel-gateway validation.
- A focused LM Studio guide covering Anthropic-compatible provider profiles, local and token-based authentication, verification, tool-use expectations, and troubleshooting.
- Focused critical-flow documentation covering CLI entrypoints, runtime bootstrap, prompt/tool execution, permissions/hooks/sandboxing, memory/session/compaction, MCP, extension discovery, the terminal protocol, `ohmo` composition, and background agents.
- Structured maintainer documentation with a docs hub, new-developer onboarding path, source and change-impact guide, evidence-backed improvement backlog, current-state architecture, extension contracts, and test selection, plus repository-local skills for general development, tool work, and provider work.
- Hooks now support a `priority` field (default `0`). Within an event, hooks run highest-priority first, and hooks sharing a priority keep their registration order. This lets users order, for example, a security-check hook ahead of a logging hook regardless of where each is declared in settings or contributed by plugins.
- `edit_file` and `write_file` in the React TUI now preview a unified diff before applying file changes, let users approve once or for the rest of the session, and skip the extra prompt automatically in `full_auto` mode.

### Fixed

- Slack gateway admission now consistently enforces the configured common `allow_from` list before
  optional DM/group policy, including the secure empty-list default.
- Codex subscription requests now pass reasoning effort separately, enabling `gpt-5.5` with `xhigh` effort instead of treating `gpt-5.5 xhigh` as an unsupported model name.
- Telegram channel now delivers replies again under `ohmo init --no-interactive` and other configs that do not write a `reply_to_message` field. `TelegramConfig` declares `reply_to_message: bool = True` so the attribute access in `TelegramChannel.send` no longer raises `AttributeError` and outbound progress/tool-hint/final messages are sent as expected. See issue #243.

## [0.1.9] - 2026-05-07

### Added

- Added a bundled `skill-creator` skill for creating, improving, and verifying OpenHarness/ohmo skills.
- User-invocable skills can now be triggered directly as slash commands, with support for skill-specific arguments and model override metadata.

### Fixed

- `oh setup` can now update the API key for an already-configured API-key provider profile instead of only changing the model.
- `oh provider edit <profile> --api-key <key>` can now replace a saved profile API key, and `oh provider add ... --api-key <key>` can store one during profile creation.

## [0.1.8] - 2026-05-06

### Added

- Built-in `nvidia` provider profile so `oh setup` offers NVIDIA NIM as a first-class OpenAI-compatible provider choice, with `NVIDIA_API_KEY` auth source, `openai/gpt-oss-120b` as the default model, and the NVIDIA NIM endpoint.
- Built-in `qwen` provider profile so `oh setup` offers Qwen (DashScope) as a first-class provider choice, with `dashscope_api_key` auth source, `qwen-plus` as the default model, and the DashScope OpenAI-compatible endpoint.
- Plugin tool discovery: plugins can now provide `BaseTool` subclasses in a `<plugin>/tools/` directory and they are auto-discovered, instantiated, and registered in the tool registry at runtime. Add `tools_dir` to `plugin.json` (defaults to `"tools"`).
- `oh --dry-run` safe preview mode for inspecting resolved runtime settings, auth state, prompt assembly, commands, skills, tools, and configured MCP servers without executing the model or tools.
- Built-in `minimax` provider profile so `oh setup` offers MiniMax as a first-class provider choice, with `MINIMAX_API_KEY` auth source, `MiniMax-M2.7` as the default model, and `MiniMax-M2.7-highspeed` in the model picker.
- Docker as an alternative sandbox backend (`sandbox.backend = "docker"`) for stronger execution isolation with configurable resource limits, network isolation, and automatic image management.
- Built-in `gemini` provider profile so `oh setup` offers Google Gemini as a first-class provider choice, with `gemini_api_key` auth source and `gemini-2.5-flash` as the default model.
- `diagnose` skill: trace agent run failures and regressions using structured evidence from run artifacts.
- OpenAI-compatible API client (`--api-format openai`) supporting any provider that implements the OpenAI `/v1/chat/completions` format, including Alibaba DashScope, DeepSeek, GitHub Models, Groq, Together AI, Ollama, and more.
- `OPENHARNESS_API_FORMAT` environment variable for selecting the API format.
- `OPENAI_API_KEY` fallback when using OpenAI-format providers.
- GitHub Actions CI workflow for Python linting, tests, and frontend TypeScript checks.
- `CONTRIBUTING.md` with local setup, validation commands, and PR expectations.
- `docs/SHOWCASE.md` with concrete OpenHarness usage patterns and demo commands.
- GitHub issue templates and a pull request template.
- React TUI assistant messages now render structured Markdown blocks, including headings, lists, code fences, blockquotes, links, and tables.
- Built-in `codex` output style for compact, low-noise transcript rendering in React TUI.

### Fixed

- Subprocess teammate spawn (`agent` tool, `task_create`) now works on Windows under Git Bash. `subprocess_backend.spawn` builds a direct-exec `argv` list and passes it through new `argv=` and `env=` kwargs on `BackgroundTaskManager.create_agent_task` / `create_shell_task`; `_start_process` then runs the executable via `asyncio.create_subprocess_exec(*argv)` with no shell in between. Previously the spawn command was a single string interpreted by `bash -lc`, which on Windows could not reliably exec a Windows-pathed Python interpreter (e.g. `C:\Users\...\python.exe`) — Git Bash's escape parser consumed the backslashes from the embedded env-prefix and, even with proper quoting, bash launched via `asyncio.create_subprocess_exec` returned `command not found` for Windows-pathed binaries that worked perfectly when invoked interactively. Bypassing the shell sidesteps the entire class of cross-platform quoting and path-translation hazard. The legacy shell-evaluated `command=` path is preserved for callers (e.g. `BashTool`) that legitimately want shell semantics. See issue #230.
- Bundled skill loader now uses `yaml.safe_load` for SKILL.md frontmatter, matching the user-skill loader. The shared parser is extracted to `openharness.skills._frontmatter` so bundled and user skills handle YAML block scalars (`>`, `|`), quoted values, and other standard YAML constructs the same way.
- Compaction now detects llama.cpp/OpenAI-compatible context overflow errors, accounts for image blocks in auto-compact token estimates, and strips image payloads from summarizer-only compaction requests.
- Large tool results are now bounded in conversation history: oversized outputs are saved under `tool_artifacts`, old MCP results become microcompactable, and context collapse trims stale tool-result payloads.
- ohmo now keeps personal memory isolated from OpenHarness project memory: `/memory` in ohmo sessions targets the ohmo workspace memory store, and ohmo runtime prompt refreshes no longer inject project memory unless explicitly requested.
- Fixed `glob` and `grep` tools hanging indefinitely when the `rg` subprocess produced enough stderr output to fill the OS pipe buffer. `stderr` is now redirected to `DEVNULL` so it is discarded rather than blocking the child process.
- Fixed `bash_tool` hanging after a timed-out command when the subprocess stdout stream stayed open. `_read_remaining_output` now applies a 2-second `asyncio.wait_for` timeout so the tool always returns promptly.
- Fixed `session_runner` background task deadlock caused by an unread `stderr=PIPE` stream. The subprocess now uses `stderr=STDOUT` so all output merges into the single readable stdout pipe.
- React TUI prompt input now treats the raw DEL byte (`0x7f`) as backward delete while preserving true forward-delete escape sequences, fixing backspace failures seen in some macOS terminal environments.
- `todo_write` tool now updates an existing unchecked item in-place when `checked=True` instead of appending a duplicate `[x]` line.

- Built-in `Explore` and `claude-code-guide` agents no longer hard-code `model="haiku"`, which caused them to fail for users on non-Anthropic providers (OpenAI, Bedrock, custom base URLs, etc.). Both agents now use `model="inherit"` so they run with whatever model the parent session is using. `build_inherited_cli_flags` is also fixed to skip the `--model` flag entirely when the value is `"inherit"`, letting the subprocess correctly inherit the parent model via the `OPENHARNESS_MODEL` environment variable instead of receiving the literal string `"inherit"` as a model name.

- React TUI spinner now stays visible throughout the entire agent turn: `assistant_complete` no longer resets `busy` state prematurely, and `tool_started` explicitly sets `busy=true` so the status bar remains active even when tool calls follow an assistant message. `line_complete` is the sole signal that ends the turn and clears the spinner.
- Skill loader now uses `yaml.safe_load` to parse SKILL.md frontmatter, correctly handling YAML block scalars (`>`, `|`), quoted values, and other standard YAML constructs instead of naive line-by-line splitting.
- `BackendHostConfig` was missing the `cwd` field, causing `AttributeError: 'BackendHostConfig' object has no attribute 'cwd'` on startup when `oh` was run after the runtime refactor that added `cwd` support to `build_runtime`.
- Shell-escape `$ARGUMENTS` substitution in command hooks to prevent shell injection from payload values containing metacharacters like `$(...)` or backticks.
- Swarm `_READ_ONLY_TOOLS` now uses actual registered tool names (snake_case) instead of PascalCase, fixing read-only auto-approval in `handle_permission_request`.
- Memory scanner now parses YAML frontmatter (`name`, `description`, `type`) instead of returning raw `---` as description.
- Memory search matches against body content in addition to metadata, with metadata weighted higher for relevance.
- Memory search tokenizer handles Han characters for multilingual queries.
- Fixed duplicate response in React TUI caused by double Enter key submission in the input handler.
- Fixed concurrent permission modals overwriting each other in TUI default mode when the LLM returns multiple tool calls in one response; `_ask_permission` now serialises callers via an `asyncio.Lock` so each modal is shown and resolved before the next one is emitted.
- Fixed React TUI Markdown tables to size columns from rendered cell text so inline formatting like code spans and bold text no longer breaks alignment.
- Fixed grep tool crashing with `ValueError` / `LimitOverrunError` when ripgrep outputs a line longer than 64 KB (e.g. minified assets or lock files). The asyncio subprocess stream limit is now 8 MB and oversized lines are skipped rather than terminating the session.
- Fixed React TUI exit leaving the shell prompt concatenated with the last TUI line. The terminal cleanup handler now writes a trailing newline (`\n`) alongside the cursor-show escape sequence so the shell prompt always starts on a fresh line.
- Reduced React TUI redraw pressure when `output_style=codex` by avoiding token-level assistant buffer flushes during streaming.

### Changed

- ohmo Feishu group routing now supports managed group creation, gateway-scoped provider/model commands, and stricter group mention handling so group conversations only wake ohmo when explicitly addressed.
- Dry-run output now reports a `ready` / `warning` / `blocked` readiness verdict, concrete `next_actions`, likely matching skills/tools for normal prompts, and richer slash-command previews for read-only vs stateful command paths.
- React TUI now groups consecutive `tool` + `tool_result` transcript rows into a single compound row: success shows the result line count inline (e.g. `→ 24L`), errors show a red icon and up to 5 lines of error detail beneath the tool row. Standalone successful tool results are suppressed to reduce transcript noise; standalone errors are still surfaced.
- README now links to contribution docs, changelog, showcase material, and provider compatibility guidance.
- README quick start now includes a one-command demo and clearer provider compatibility notes.
- README provider compatibility section updated to include OpenAI-format providers.

## [0.1.7] - 2026-04-18

### Fixed

- Install script now links `oh`, `ohmo`, and `openharness` into `~/.local/bin` instead of prepending the virtualenv `bin` directory to `PATH`, which avoids overriding Conda-managed shells while preserving global command discovery.
- React TUI prompt now supports `Shift+Enter` for inserting a newline without submitting the current prompt.
- React TUI busy-state animation is less error-prone on Windows terminals: the extra pseudo-animation line was removed, Windows now uses conservative ASCII spinner frames, and the spinner interval was slightly slowed to reduce flashing.

## [0.1.0] - 2026-04-01

### Added

- Initial public release of OpenHarness.
- Core agent loop, tool registry, permission system, hooks, skills, plugins, MCP support, and terminal UI.
