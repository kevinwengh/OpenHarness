# Glossary

| Term | Meaning in this repository |
| --- | --- |
| Agent turn | One provider request/response iteration inside a query; tool requests cause more turns |
| Query | A submitted user message processed until a final response, error, interruption, or turn limit |
| `RuntimeBundle` | Lifecycle-owned collection of engine, client, registries, hooks, MCP, settings, and persistence adapters |
| Composition root | `ui/runtime.py::build_runtime()`, where runtime dependencies are assembled |
| Provider profile | Saved workflow selecting provider family, API format, auth source, model, endpoint, and limits |
| API format | Wire-conversion family such as Anthropic Messages or OpenAI chat completions |
| Tool | Model-callable typed asynchronous operation returning `ToolResult` |
| Slash command | Host-local command parsed before normal prompt submission |
| Skill | Markdown instructions/references discoverable by name; not executable Python by itself |
| Plugin | Manifest-rooted bundle that may contribute instructions, commands, agents, tools, hooks, or MCP configuration |
| Hook | Lifecycle observer/policy action; command, HTTP, prompt, or agent hook |
| MCP | Model Context Protocol connection exposing external tools/resources |
| Permission mode | Default, plan, or full-auto policy applied after hard and explicit rules |
| Sandbox | Optional alternate environment used by supported tool paths; not a universal runtime wrapper |
| Session | Persistable conversation and selected continuation metadata |
| Memory | Durable project/personal knowledge selected into prompts; distinct from session history |
| Compaction | Reduction/summarization of conversation context while preserving provider-valid tool pairs |
| Task | Background shell or agent process managed outside the foreground query |
| Swarm/team | Coordinated agents using local backends, mailboxes, permissions, and optional worktrees |
| Bridge session | Core-managed child command/session with captured output; distinct from ohmo's gateway bridge |
| Channel bridge | Consumer connecting normalized channel messages to an engine/runtime and outbound bus |
| Gateway | Long-lived ohmo service containing channel manager, message bridge, router, and runtime pool |
| Session key | Derived conversation-isolation identifier for channel/chat/thread/sender scope |
| Autopilot | Repository task intake/execution/verification/PR pipeline under `.openharness/autopilot` |
| Worktree | Separate Git checkout used to isolate agent/autopilot mutation from the primary checkout |
| Dry-run | Static, non-model readiness preview; not proof that credentials/endpoints work |
| Live evaluation | Opt-in test using a real provider/model or external service |

Do not use “provider,” “profile,” “API format,” and “model” interchangeably. Provider/profile names
are configuration labels; compatibility is proven only by endpoint behavior, request/response
conversion, replay, and tests.
