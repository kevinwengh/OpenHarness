# Change impact map

Read only the rows relevant to the requested change, then inspect their source and tests.

| Change | Primary owner | Also inspect |
| --- | --- | --- |
| CLI option/subcommand | `src/openharness/cli.py` | settings, runtime, entrypoint/command tests, README |
| Slash command | `commands/registry.py` | `ui/runtime.py` command rendering and command tests |
| Agent loop/message | `engine/query.py`, `engine/messages.py` | stream events, permissions, hooks, compact, provider replay, engine tests |
| Runtime lifecycle | `ui/runtime.py` | MCP/API/sandbox cleanup and UI runtime tests |
| Settings/profile | `config/settings.py` | auth, CLI setup, dry-run, redaction, config tests |
| Memory/session | `memory/`, `services/session_*` | compact, resume, ohmo backend, persistence tests |
| Skill/plugin/hook | matching subsystem | prompt assembly, commands, project trust, loader/lifecycle tests |
| MCP | `mcp/` | runtime registry adapters, plugin namespacing, MCP tests |
| Sandbox/permission | `sandbox/`, `permissions/` | tool path/command metadata and denial tests |
| Task/swarm | `tasks/`, `swarm/`, `coordinator/` | permissions, worktrees, subprocess cleanup, platform tests |
| Channel/bridge | `channels/`, `bridge/` | ohmo gateway, auth/mentions, attachment handling |
| React terminal | `frontend/terminal` | `ui/backend_host.py`, launcher, protocol/UI tests, wheel packaging |
| Autopilot | `autopilot/` | `.github/workflows`, dashboard source/snapshot, autopilot tests |
| ohmo | `ohmo/` | shared runtime APIs but no reverse core dependency |
