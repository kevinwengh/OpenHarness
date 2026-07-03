# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenHarness is an open-source Python agent harness that provides the infrastructure to wrap an LLM into a functional agent (tools, memory, permissions, skills, multi-agent coordination). It ships two apps:

- **`oh`** (aliases: `oh`, `openh`) — the main CLI agent harness. Entry: `src/openharness/cli.py` (`app` / `main`).
- **`ohmo`** — a personal-agent app with gateway, channels (Telegram/Slack/Discord/Feishu), and `~/.ohmo` workspace. Entry: `ohmo/cli.py`.

Both are installed as console scripts via `pyproject.toml`.

## Dev Commands

```bash
# Install deps
uv sync --extra dev

# Run all tests
uv run pytest -q

# Run a single test
uv run pytest tests/test_tools/test_bash.py -v

# Lint
uv run ruff check src tests scripts

# Type check (optional — not yet a required CI gate)
uv run mypy src/openharness

# Frontend sanity check
cd frontend/terminal && npx tsc --noEmit && cd ../..

# Run the harness itself
uv run oh
uv run oh -p "Explain this codebase"
uv run oh --dry-run
uv run ohmo gateway run
```

## Architecture

### Core subsystems (under `src/openharness/`)

| Subsystem | What it does | Key files |
|-----------|-------------|-----------|
| **engine** | Agent loop: query → stream → tool-call → loop | `engine/query_engine.py` |
| **tools** | 43+ tools (Bash, Read, Write, Edit, Glob, Grep, WebFetch, Agent, etc.) | `tools/` — each tool is a class extending `BaseTool` |
| **commands** | 54+ slash commands (`/help`, `/commit`, `/plan`, etc.) | `commands/registry.py` |
| **skills** | On-demand `.md` skill loading from bundled/user/project locations | `skills/` |
| **permissions** | Multi-level permission modes + path rules + command deny lists | `permissions/` |
| **hooks** | PreToolUse / PostToolUse lifecycle hooks | `hooks/` |
| **plugins** | Plugin system (commands + hooks + agents + MCP) compatible with claude-code plugins | `plugins/` |
| **mcp** | Model Context Protocol client (stdio + HTTP transport) | `mcp/` |
| **memory** | Persistent cross-session memory (MEMORY.md) | `memory/` |
| **coordinator** | Subagent spawning, team registry, background task lifecycle | `coordinator/` |
| **tasks** | Background task management (create/get/list/update/stop) | `tasks/` |
| **prompts** | System prompt assembly, CLAUDE.md discovery, context compression | `prompts/` |
| **config** | Multi-layer settings, migrations, profile management | `config/settings.py`, `config/paths.py` |
| **api** | Multi-provider API clients (Anthropic, OpenAI, Copilot, Codex, Moonshot, etc.) | `api/` |
| **auth** | Auth manager, credential storage, provider flows, external CLI binding | `auth/` |
| **ui** | React TUI backend protocol + frontend server | `ui/` |
| **channels** | ohmo channel implementations (Telegram, Slack, Discord, Feishu) | `channels/` |
| **autopilot** | Repo-level autonomous task queue (scan issues/PRs → cards → run → PR) | `autopilot/` |

### Entry points and flow

```
cli.py (typer app)
  ├── main()           → run_repl() / run_print_mode() / run_task_worker()
  ├── setup_cmd        → interactive provider setup flow
  ├── provider App     → list/use/add/edit/remove profiles
  ├── auth App         → login/logout/status/switch
  ├── mcp App          → list/add/remove MCP servers
  ├── plugin App       → install/uninstall plugins
  ├── cron App         → scheduler daemon + job management
  ├── autopilot App    → repo autopilot cards/journal/scan
  └── config App       → show/set settings
```

The `RuntimeBundle` (under `openharness/runtime.py`) is the central wiring object that connects settings, API client, tool registry, command registry, permission checker, hooks, and skill registry.

### Key patterns

- **Tools** extend `BaseTool` with Pydantic `input_model`, self-describing JSON Schema, and `execute()` async method.
- **Commands** are registered via `CommandRegistry` and can be slash-prefixed (`/commit`) or remote-invocable for ohmo channels.
- **Skills** are `.md` files loaded on-demand from bundled, user, ohmo, project, or plugin paths.
- **Permissions** have three modes: `default` (ask), `full_auto` (allow), `plan` (block writes). Path rules and denied commands are configurable in `settings.json`.
- **Providers** are named profiles with per-profile auth. Built-in families: Anthropic-compatible, OpenAI-compatible, Claude Subscription, Codex Subscription, GitHub Copilot.
- **ohmo** has its own workspace (`~/.ohmo/`), `soul.md` personality, `BOOTSTRAP.md` ritual, gateway config, and channel adapters. It reuses the same OpenHarness engine under the hood.

### Frontend

The React TUI lives in `frontend/terminal/`. The backend serves a WebSocket protocol that the frontend consumes. Build: `npm ci && npm run build` in `frontend/terminal/`.

## Testing

- Unit/integration tests: `tests/` (114+ tests). Run with `uv run pytest`.
- Harness E2E: `python scripts/test_harness_features.py`.
- Real skills/plugins E2E: `python scripts/test_real_skills_plugins.py`.
- Tests are organized by subsystem: `test_tools/`, `test_commands/`, `test_permissions/`, `test_engine/`, `test_api/`, `test_auth/`, `test_mcp/`, `test_skills/`, `test_plugins/`, `test_ui/`, `test_ohmo/`, etc.

## CI

`/.github/workflows/ci.yml` runs: Python tests (3.10 + 3.11), ruff lint, frontend TypeScript check.

## PR expectations

- Scope PRs. Include problem, change, and verification.
- Add/update tests for behavior changes.
- Add a short `Unreleased` entry in `CHANGELOG.md` for user-visible changes.
- If improving type coverage, run `uv run mypy src/openharness` (not yet a required gate).
