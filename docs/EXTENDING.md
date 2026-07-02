# Extending OpenHarness

OpenHarness has several extension surfaces. Choose the narrowest one that fits:

| Need | Extension surface |
| --- | --- |
| Give the model a new executable capability | Built-in tool or plugin tool |
| Give the model reusable instructions | Skill |
| Bundle skills, commands, agents, hooks, tools, and MCP | Plugin |
| Add a model/API family | Provider registry/client/auth |
| Add an external tool/resource server | MCP configuration |
| Enforce or observe lifecycle policy | Hook |
| Add a chat transport | Channel |
| Add a local slash action | Command registry or plugin command |

## Add a built-in tool

1. Create `src/openharness/tools/<name>_tool.py`.
2. Define a Pydantic input model with descriptions and constraints.
3. Subclass `BaseTool`; set a stable snake-case `name` and a model-useful `description`.
4. Implement `async execute(arguments, context) -> ToolResult`.
5. Override `is_read_only()` only when every effect of that invocation is read-only.
6. Register the tool in `create_default_tool_registry()` in `src/openharness/tools/__init__.py`.
7. Add focused tests in `tests/test_tools/` and integration coverage when permissions, hooks, sandboxing, or metadata are involved.

Minimal shape:

```python
from pydantic import BaseModel, Field

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class ExampleToolInput(BaseModel):
    value: str = Field(description="Value to inspect")


class ExampleTool(BaseTool):
    name = "example"
    description = "Inspect an example value."
    input_model = ExampleToolInput

    async def execute(
        self,
        arguments: ExampleToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        return ToolResult(output=arguments.value)

    def is_read_only(self, arguments: ExampleToolInput) -> bool:
        return True
```

Use the `openharness-add-tool` skill for the full checklist.

## Add a project skill

Create `.claude/skills/<skill-name>/SKILL.md`. OpenHarness also discovers `.openharness/skills` and `.agents/skills` from the working directory upward to the Git root.

```markdown
---
name: example-skill
description: Explain what the skill does and the concrete requests that should trigger it.
---

# Example skill

Write concise imperative instructions. Link optional detailed material from
`references/` so it is loaded only when needed.
```

Names use lowercase letters, digits, and hyphens. Keep the trigger description in frontmatter. A project skill with the same name as a broader bundled/user skill overrides it because project roots load later. Validate repository skills with the skill-creator validator:

```bash
python /path/to/skill-creator/scripts/quick_validate.py .claude/skills/<skill-name>
```

Runtime-bundled skills for all installed users live in `src/openharness/skills/bundled/content/` and use the existing bundled Markdown format.

## Add a plugin

Plugins may be user-installed under `~/.openharness/plugins/<name>` or project-local under `.openharness/plugins/<name>`. Project plugins are disabled by default because Python tools and hooks can execute code.

Minimal layout:

```text
example-plugin/
├── plugin.json
├── skills/
│   └── example/SKILL.md
├── commands/
│   └── example.md
├── agents/
│   └── reviewer.md
├── tools/
│   └── example.py
├── hooks.json
└── mcp.json
```

Minimal manifest:

```json
{
  "name": "example-plugin",
  "version": "0.1.0",
  "description": "Example OpenHarness plugin",
  "enabled_by_default": true
}
```

The loader also accepts `.claude-plugin/plugin.json`, `.mcp.json`, and structured `hooks/hooks.json`. Consult `src/openharness/plugins/schemas.py`, `loader.py`, and `tests/test_plugins/` before relying on less common manifest fields.

Python tool files are imported dynamically. Export either tool instances/classes in the forms recognized by `_load_plugin_tools()` and verify with plugin lifecycle tests. Keep plugin imports self-contained and fail with actionable messages when optional dependencies are absent.

## Add or modify a provider

There are two cases:

- OpenAI-compatible provider with existing authentication: add a `ProviderSpec` to `src/openharness/api/registry.py`, then add setup/profile UX only if a first-class workflow is justified.
- New wire protocol or authentication mechanism: implement the streaming client contract, route it in `ui/runtime.py`, model it in settings/auth flows, and test all translations.

Do not stop at provider detection. Verify registry priority, defaults, settings/profile materialization, credential resolution, dry-run status, streaming text and tool calls, usage, errors, and replay of assistant tool-call messages. Use the `openharness-add-provider` skill.

## Add MCP configuration

MCP servers can come from `settings.mcp_servers` or an enabled plugin. The manager supports stdio, HTTP, and WebSocket configurations defined in `src/openharness/mcp/types.py`.

Use the CLI for user configuration:

```bash
oh mcp add --help
oh mcp list
oh --dry-run --output-format json
```

MCP tools are adapted into the normal tool registry and therefore pass through the same query-loop and permission machinery. Plugin server names are namespaced as `<plugin>:<server>`.

## Add a hook

Supported events are defined by `HookEvent`: session start/end, pre/post compact, pre/post tool use, user prompt submit, notification, stop, and subagent stop.

Hooks can be command or prompt definitions. Pre-tool hooks can block execution. Keep command hooks bounded with timeouts, treat `$ARGUMENTS` as serialized untrusted input, and test priority plus failure policy. See `src/openharness/hooks/schemas.py`, `executor.py`, and `tests/test_hooks/`.

## Add a channel

1. Implement `BaseChannel` in `src/openharness/channels/impl/`.
2. Translate platform events into `InboundMessage` and outbound responses from `OutboundMessage`.
3. Register/configure the adapter in `ChannelManager` and channel config models.
4. Keep credentials out of logs and validate group/mention authorization before processing content.
5. Add deterministic adapter/security tests; keep live SDK tests opt-in.
6. If the transport is exposed through ohmo, add its configuration wizard and gateway coverage.

Check `src/openharness/channels/UPSTREAM` before broad channel refactors because some channel implementations may be synchronized from another codebase.

## Add a slash command

Built-in commands are registered in `create_default_command_registry()` in `src/openharness/commands/registry.py`. A command receives parsed text plus `CommandContext` and returns `CommandResult`. Prefer a plugin command when the behavior is optional or domain-specific.

Commands that alter provider/model/settings may require a runtime refresh. Commands that launch model work return the appropriate prompt/continuation signal rather than invoking the client directly. Add registry and flow tests.

## Add a session backend

Implement `SessionBackend` from `src/openharness/services/session_backend.py`, including save, latest/list/by-ID load, storage directory, and Markdown export. Persist only JSON-safe tool metadata required for continuation and sanitize messages during read/write.

## Documentation and tests

Every extension should update the nearest documentation and tests. If it changes a boundary or flow, update [ARCHITECTURE.md](ARCHITECTURE.md). Select validation from [TESTING.md](TESTING.md).
