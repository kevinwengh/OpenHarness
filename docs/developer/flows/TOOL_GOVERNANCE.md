# Tool execution, permissions, hooks, and sandboxing

## Question answered

After a model requests a tool, what checks run before effects occur, where does sandboxing happen,
and how is the result returned safely?

## Execution order

```mermaid
sequenceDiagram
    participant Loop as Query loop
    participant Hooks
    participant Registry
    participant Policy
    participant UI
    participant Tool
    participant Sandbox

    Loop->>Hooks: pre tool event with raw input
    alt hook blocks
        Hooks-->>Loop: error result with same call ID
    else hook allows
        Loop->>Registry: resolve exact tool name
        Registry-->>Loop: tool contract
        Loop->>Loop: validate Pydantic input
        Loop->>Policy: evaluate path, command, and mode
        opt confirmation required
            Policy->>UI: request approval
            UI-->>Policy: approve or reject
        end
        alt denied
            Policy-->>Loop: error result with same call ID
        else allowed
            Loop->>Tool: execute parsed input
            opt effect uses process abstraction
                Tool->>Sandbox: route to host, SRT, or Docker
                Sandbox-->>Tool: process result
            end
            Tool-->>Loop: ToolResult
            Loop->>Loop: bound output and record carryover
            Loop->>Hooks: post tool event
        end
    end
```

### Function-level governance sequence

1. `run_query()` obtains `ToolUseBlock` values from the completed assistant message and calls
   `_execute_tool_call(context, name, id, input)` for each.
2. `_execute_tool_call()` delegates the common lifecycle to `GovernedToolExecutor.execute()`.
   The executor first awaits `HookExecutor.execute(PRE_TOOL_USE, ...)`. A blocked
   `AggregatedHookResult` returns immediately, before registry lookup or Pydantic parsing.
3. `ToolRegistry.get()` performs exact-name resolution. The selected tool's
   `input_model.model_validate()` converts untrusted provider JSON into the typed argument model.
4. `resolve_permission_file_path()` resolves common path fields against the executor cwd, while
   `extract_permission_command()` obtains the command string used by deny patterns.
5. `PermissionChecker.evaluate()` applies hard-sensitive paths, explicit tool rules, path/command
   rules, mode, and `is_read_only()` in its documented precedence.
6. A confirmation decision fires `HookEvent.NOTIFICATION` and awaits the host-owned
   `permission_prompt`. The engine never fabricates an interactive approval.
7. The governed executor awaits `BaseTool.execute(parsed_input, ToolExecutionContext(...))`. Tools that spawn
   processes use `create_shell_subprocess()`; that helper chooses Docker routing or calls
   `wrap_command_for_sandbox()` for SRT/host behavior.
8. The executor bounds large output, then invokes the query loop's result observer to update
   session carryover before `POST_TOOL_USE` observes the normalized result. This callback keeps
   generic governance reusable without changing the historical hook-visible ordering.
9. The returned `ToolResultBlock.tool_use_id` always equals the provider's original tool-use ID, so
   the next provider request is structurally valid even for denial and error paths.

## 1. The tool contract

Every built-in, plugin, and MCP adapter is a `BaseTool` with:

- stable `name` and model-facing `description`;
- Pydantic `input_model` used both for API schema generation and runtime validation;
- asynchronous `execute(arguments, context) -> ToolResult`;
- conservative `is_read_only(arguments)` classification.

`ToolExecutionContext` supplies the resolved session cwd, runtime metadata, and hook executor.
`ToolResult` supplies text output, an error flag, and optional structured metadata. Expected
operational failures should return `ToolResult(is_error=True)` instead of escaping as exceptions.

## 2. Hooks run before registry and permission checks

`GovernedToolExecutor.execute()` invokes `pre_tool_use` hooks first with the raw tool name and input. A blocking
aggregate hook result returns an error result immediately. Hooks can be command, HTTP, prompt, or
agent definitions selected by event and matcher; registry priority determines order.

This ordering lets a security/policy hook block even unknown or malformed tool requests. It also
means hook inputs are untrusted model output. Command hooks shell-escape `$ARGUMENTS` and have
bounded execution behavior.

## 3. Input validation precedes permission classification

The registry resolves the tool by exact name. Its Pydantic model validates the raw dictionary. The
engine then derives a policy path from common `file_path`, `path`, or `root` fields and resolves
relative paths against the runtime cwd. It similarly extracts a `command` field for command-deny
rules.

Read-only status is determined from the parsed invocation, not solely the tool name. For example, a
configuration tool may read in one mode and mutate in another.

## 4. Permission decision precedence

`PermissionChecker.evaluate()` applies rules in this order:

1. Built-in sensitive credential paths: always denied, including full-auto mode.
2. Explicit denied tools.
3. Explicit allowed tools.
4. Matching path deny rules.
5. Matching denied-command patterns.
6. Full-auto mode: allow remaining calls.
7. Read-only invocation: allow.
8. Plan mode: deny mutation.
9. Default mode: require confirmation for mutation.

When confirmation is required, the engine emits a notification hook and awaits the UI-provided
`permission_prompt`. No callback means the call stays denied. React serializes concurrent permission
dialogs so multiple tool calls cannot overwrite one another.

## 5. Sandboxing is not a universal wrapper in the query loop

The engine does not wrap arbitrary `BaseTool.execute()` calls in a sandbox. Sandboxing is applied by
effect-owning implementations and shared process-launch helpers:

- shell/process tools call `create_shell_subprocess()`, which routes according to sandbox settings;
- sandbox-runtime (`srt`) can wrap process argv with generated filesystem/network policy;
- Docker mode starts a session during runtime bootstrap and supported tools route operations through
  the Docker backend;
- hooks that execute commands use the shared sandbox-aware process path;
- pure in-process tools remain in the OpenHarness process and must enforce their own boundary checks.

This distinction matters when adding a tool: registering it does not automatically make arbitrary
Python side effects sandboxed. The tool owner must use the supported sandbox/process abstraction and
test both enabled and unavailable behavior.

## 6. Result normalization and continuation

After execution, large output may be saved as an artifact and replaced by bounded inline content.
The engine records selected carry-over metadata (read files, artifacts, skills, background agents,
verified work, and task focus), fires `post_tool_use`, and constructs a `ToolResultBlock` carrying the
original tool-use ID.

The post hook observes the result but does not replace it. The result returns to the model on the
next query-loop turn, allowing the model to recover from denials and operational failures.

## Failure behavior to preserve

- Unknown tool: error result, never arbitrary dynamic import.
- Invalid arguments: error result with validation detail.
- Sensitive path: hard denial before configured allow rules.
- User rejection: matching error result; no repeated execution.
- Tool exception: caught by the surrounding loop and converted to an error result.
- Parallel calls: every tool-use ID receives a result even if one sibling raises.
- Sandbox required but unavailable: normalized failure rather than silent host execution when
  `fail_if_unavailable` is enabled.

## Where to change behavior

| Concern | Owner |
| --- | --- |
| Tool schema/effects | matching module under `src/openharness/tools/` |
| General tool contract/registry | `src/openharness/tools/base.py`, `src/openharness/tools/__init__.py` |
| Reusable lifecycle ordering | `src/openharness/tools/executor.py` |
| Query-loop carryover integration | `src/openharness/engine/query.py` |
| Permission precedence | `src/openharness/permissions/checker.py` |
| Hook matching/execution | `src/openharness/hooks/loader.py`, `src/openharness/hooks/executor.py` |
| Process isolation | `src/openharness/sandbox/`, `src/openharness/utils/shell.py`, effect-owning tool |

## Source and symbol reference

| Responsibility | File | Symbol |
| --- | --- | --- |
| Turn dispatch and parallel sibling handling | `src/openharness/engine/query.py` | `run_query()` |
| Per-call governance | `src/openharness/engine/query.py` | `_execute_tool_call()` |
| Reusable governance sequence | `src/openharness/tools/executor.py` | `GovernedToolExecutor.execute()` |
| Policy metadata extraction | `src/openharness/tools/executor.py` | `resolve_permission_file_path()`, `extract_permission_command()` |
| Tool contract | `src/openharness/tools/base.py` | `BaseTool`, `ToolExecutionContext`, `ToolResult` |
| Registry schema/export | `src/openharness/tools/base.py` | `ToolRegistry.get()`, `to_api_schema()` |
| Permission precedence | `src/openharness/permissions/checker.py` | `PermissionChecker.evaluate()` |
| Hook aggregation | `src/openharness/hooks/executor.py` | `HookExecutor.execute()` |
| Process routing | `src/openharness/utils/shell.py` | `create_shell_subprocess()` |
| SRT routing and fallback | `src/openharness/sandbox/adapter.py` | `get_sandbox_availability()`, `wrap_command_for_sandbox()` |
| Docker execution session | `src/openharness/sandbox/docker_backend.py` | `DockerSandboxSession` |
| Query output-offload callback | `src/openharness/engine/query.py` | `_offload_tool_output_if_needed()` |

## Verification map

- `tests/test_tools/`: schema, execution, error, and classification.
- `tests/test_permissions/test_checker.py`: precedence and sensitive paths.
- `tests/test_hooks/`: blocking, priority, matching, and command escaping.
- `tests/test_sandbox/`: routing, availability, Docker behavior, and paths.
- `tests/test_engine/test_query_engine.py`: full lifecycle and parallel results.
