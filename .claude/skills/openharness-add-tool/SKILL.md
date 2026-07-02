---
name: openharness-add-tool
description: Add, modify, debug, or review an OpenHarness built-in or plugin model tool, including its Pydantic schema, registry wiring, permissions, hooks, sandbox behavior, metadata, error handling, and tests. Use whenever work creates a new tool capability, changes tool execution semantics, exposes an operation to the model, or loads Python tools from plugins.
---

# Add an OpenHarness tool

Build a predictable model-facing contract and validate its full execution path.

## Choose the extension type

- Add a built-in tool under `src/openharness/tools/` when every installation needs the capability.
- Add a plugin tool when the capability is optional, domain-specific, or depends on extra packages.
- Prefer MCP when an external service already exposes a maintained MCP server.

Read `docs/EXTENDING.md`, `src/openharness/tools/base.py`, and [references/tool-checklist.md](references/tool-checklist.md).

## Implement a built-in tool

1. Define a constrained Pydantic input model. Add field descriptions that help the model choose valid arguments.
2. Subclass `BaseTool` and define a unique snake-case `name`, precise `description`, and `input_model`.
3. Implement asynchronous `execute()` and always return `ToolResult` for expected operational failures.
4. Use `ToolExecutionContext.cwd` rather than process-global working-directory assumptions.
5. Override `is_read_only()` only if that exact invocation cannot mutate local or external state.
6. Attach file path and command information through the conventions used by comparable tools so permission and sandbox policy can reason about the call.
7. Register the instance in `create_default_tool_registry()`.

## Implement a plugin tool

1. Inspect `_load_plugin_tools()` in `src/openharness/plugins/loader.py` for accepted exports.
2. Keep imports safe when optional dependencies are unavailable.
3. Do not assume project plugins are enabled; preserve `allow_project_plugins=false` as the default.
4. Add plugin lifecycle coverage as well as tool behavior coverage.

## Verify

1. Test API schema generation and required/optional arguments.
2. Test success, expected failure, invalid input, and accurate read-only classification.
3. Test path/command permissions and sensitive-path denial when relevant.
4. Test hook ordering or blocking if the tool changes execution lifecycle.
5. Test sandbox routing for filesystem/shell/process behavior.
6. Add an engine integration test when model tool-result continuation or metadata is involved.
7. Run the focused tool tests, related permission/sandbox/plugin tests, Ruff, and the full suite as appropriate.
8. Update README tool lists, `docs/EXTENDING.md`, architecture, and changelog only when their claims change.

Do not use a real model merely to prove deterministic tool behavior. Use `harness-eval` only when model selection/use of the new tool is part of the requested acceptance criteria.
