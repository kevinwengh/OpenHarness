# Built-in tools and slash commands

This reference is based on `tools.create_default_tool_registry()` and
`commands.registry.create_default_command_registry()`. The current default registry contains 39
built-in model tools and 69 built-in slash commands. MCP servers, enabled plugins, and user/project
skills can add runtime-dependent tools or commands, so static totals are not capability guarantees.

## Model tools

| Group | Registered names | Ownership / effects |
| --- | --- | --- |
| Shell/files | `bash`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `notebook_edit` | filesystem/process; tool-specific sandbox and permission metadata |
| Code/context | `lsp`, `brief`, `config`, `todo_write` | code navigation, bounded text, runtime/project state |
| Web/media | `web_fetch`, `web_search`, `image_to_text`, `image_generation` | external network/model services; media artifacts |
| Interaction | `ask_user_question`, `sleep` | host callback or cooperative wait |
| Skills/discovery | `skill`, `tool_search` | loads instructions or discovers deferred tools |
| Workflow modes | `enter_plan_mode`, `exit_plan_mode`, `enter_worktree`, `exit_worktree` | mutates runtime/worktree mode |
| Cron | `cron_create`, `cron_list`, `cron_delete`, `cron_toggle`, `remote_trigger` | durable schedules and remote notification intent |
| Tasks | `task_create`, `task_get`, `task_list`, `task_stop`, `task_output`, `task_update` | background process/agent work |
| Coordination | `agent`, `send_message`, `team_create`, `team_delete` | subprocess/in-process agents, mailboxes, teams |
| MCP control | `mcp_auth` | reconnect/auth configuration |

When an MCP manager exists, `list_mcp_resources`, `read_mcp_resource`, and one adapter per connected
MCP tool are registered in addition to the 39 defaults.

Every built-in tool subclasses `BaseTool`, declares a Pydantic `input_model`, implements async
`execute()`, returns `ToolResult`, and provides an argument-aware `is_read_only()` classification.
The engine, not the tool, owns validation, permission approval, lifecycle stream events, and
provider replay. Tools own operational error normalization, path resolution from `context.cwd`, and
effect-specific sandbox routing.

## Tool execution references

- Contract: `src/openharness/tools/base.py`
- Registration: `src/openharness/tools/__init__.py::create_default_tool_registry()`
- Governance: `src/openharness/engine/query.py::_execute_tool_call()`
- Permissions: `src/openharness/permissions/checker.py::PermissionChecker.evaluate()`
- Detailed flow: [Tool governance](../developer/flows/TOOL_GOVERNANCE.md)

## Slash commands

Slash commands run locally through `CommandRegistry` before ordinary prompt submission. A handler
returns `CommandResult`, which can display text, refresh runtime configuration, submit a generated
prompt, continue pending work, or change host state.

| Group | Commands |
| --- | --- |
| Session/navigation | `/help`, `/exit`, `/clear`, `/status`, `/context`, `/summary`, `/compact`, `/continue`, `/stop` |
| Usage/version | `/version`, `/cost`, `/usage`, `/stats`, `/release-notes`, `/upgrade` |
| Memory/session files | `/dream`, `/memory`, `/resume`, `/session`, `/export`, `/share`, `/tag`, `/rewind`, `/files`, `/init` |
| Authentication/config | `/login`, `/logout`, `/config`, `/provider`, `/model`, `/doctor`, `/privacy-settings`, `/rate-limit-options` |
| Extensions | `/hooks`, `/skills`, `/mcp`, `/plugin`, `/reload-plugins`, plus user-invocable skill commands |
| Workflow skills | `/commit`, `/debug`, `/diagnose`, `/plan`, `/review`, `/simplify`, `/skill-creator`, `/test`, `/ship` |
| Runtime modes | `/permissions`, `/fast`, `/effort`, `/passes`, `/turns` |
| UI | `/theme`, `/output-style`, `/keybindings`, `/vim`, `/voice`, `/onboarding` |
| Git/project | `/diff`, `/branch`, `/issue`, `/pr_comments`, `/feedback` |
| Background/agents | `/agents`, `/subagents`, `/tasks`, `/autopilot` |
| Bridge | `/bridge` |

`CommandRegistry.list_commands()` and `/help` are authoritative for the current host. Some commands
are local-only or unsafe for remote invocation; `ohmo/gateway/runtime.py` checks
`remote_invocable` and an explicit administrative opt-in before dispatch.

## Runtime variability

- Enabled plugin commands are namespaced/registered during runtime construction.
- User-invocable skills become slash commands through `lookup_skill_slash_command()`.
- MCP tools are named from server/tool segments and depend on successful connection.
- ohmo adds application-specific tools and filters commands for remote authority.
- Deferred tool discovery can expose capabilities not present in the eager default registry.

Do not use a README count to decide whether a particular capability exists. Inspect the active
registry through dry-run/status/help or its owning source.
