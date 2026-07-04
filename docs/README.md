# OpenHarness documentation

This page is the entry point for repository documentation. It separates the shortest path for a
new contributor from detailed reference material and generated artifacts.

## New contributor path

Read these in order:

1. [Developer onboarding](developer/ONBOARDING.md) — set up an isolated environment, run the
   repository, and choose a first change.
2. [Codebase guide](developer/CODEBASE_GUIDE.md) — follow a request through composition, the agent
   loop, tools, persistence, and user interfaces.
3. [Critical runtime flows](developer/flows/README.md) — detailed, focused traces for CLI launch,
   runtime construction, prompts/tools, memory, MCP, extensions, UI, `ohmo`, and background agents.
4. [Architecture](ARCHITECTURE.md) — current system boundaries, flows, state ownership, contracts,
   and known unknowns.
5. [Development guide](DEVELOPMENT.md) — maintainer workflow, conventions, risky seams, and release
   considerations.
6. [Testing and validation](TESTING.md) — select checks that match the affected subsystem.

The [developer guide index](developer/README.md) offers shorter reading tracks for backend,
provider, extension, UI, and `ohmo` work.

## Reference by task

| Goal | Start here | Then inspect |
| --- | --- | --- |
| Understand how `oh` launches | [CLI entrypoints](developer/flows/CLI_ENTRYPOINTS.md) | `pyproject.toml`, `cli.py`, and `ui/app.py` |
| Trace an entire interactive `uv run oh` session | [Interactive frontend/backend flow](developer/flows/INTERACTIVE_OH_FRONTEND_BACKEND_E2E.md) | Python launcher, React terminal, backend host, protocol, interruption, and shutdown |
| Trace prompt memory, tools, compaction, and persistence | [Prompt lifecycle end to end](developer/flows/PROMPT_MEMORY_TOOLS_COMPACTION_E2E.md) | Runtime prompt assembly, query engine, compactor, memory, and session storage |
| Change the model/tool loop | [Architecture](ARCHITECTURE.md#main-runtime-flows) | `src/openharness/engine/query.py` and `tests/test_engine/` |
| Add a tool, skill, plugin, hook, or MCP server | [Extending OpenHarness](EXTENDING.md) | The matching source and `tests/test_*` directory |
| Understand or change a provider client | [Provider integration index](developer/providers/README.md) | Anthropic, OpenAI-compatible, Codex subscription, and GitHub Copilot deep references |
| Add a provider or profile | [Codebase guide](developer/CODEBASE_GUIDE.md#provider-and-authentication-path) | `src/openharness/api/`, `auth/`, `config/`, and provider tests |
| Use a local LM Studio model through the Anthropic API | [LM Studio Anthropic-compatible guide](providers/LM_STUDIO_ANTHROPIC.md) | Provider profiles, local authentication, verification, and troubleshooting |
| Manually validate LM Studio across `oh`, the terminal, and `ohmo` | [LM Studio local manual test flow](testing/LM_STUDIO_LOCAL_MANUAL_TEST.md) | Layered pass criteria, failure localization, and state ownership |
| Change permissions or sandboxing | [Codebase guide](developer/CODEBASE_GUIDE.md#tool-execution-and-safety-path) | `src/openharness/permissions/`, `sandbox/`, and their tests |
| Change the terminal UI | [Development guide](DEVELOPMENT.md#pythontypescript-ui-protocol) | `src/openharness/ui/`, `frontend/terminal/`, and `tests/test_ui/` |
| Understand or change `ohmo` | [`ohmo` developer reference](developer/ohmo/README.md) | Dedicated lifecycle guides, `ohmo/`, and `tests/test_ohmo/` |
| Trace memory, MCP, UI, or background agents | [Critical runtime flows](developer/flows/README.md) | The source/test map in the selected flow |
| Decide what to improve next | [Improvement backlog](developer/IMPROVEMENTS.md) | Evidence and completion criteria under each item |
| Prepare a contribution | [Contributing guide](../CONTRIBUTING.md) | [Testing and validation](TESTING.md) |

## Document ownership

| Document | Keep it synchronized when |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | A boundary, main flow, state owner, or invariant changes |
| [Development guide](DEVELOPMENT.md) | The maintainer workflow, supported toolchain, or release process changes |
| [Extending OpenHarness](EXTENDING.md) | An extension contract, registration step, or trust rule changes |
| [Testing and validation](TESTING.md) | CI, test selection, or an environment-specific check changes |
| [Codebase guide](developer/CODEBASE_GUIDE.md) | Entrypoints or subsystem ownership move |
| [Critical runtime flows](developer/flows/README.md) | A documented lifecycle, call order, state owner, or failure path changes |
| [`ohmo` developer reference](developer/ohmo/README.md) | An ohmo workspace, local runtime, memory, persistence, gateway, routing, media, command, or managed-group workflow changes |
| [Provider integration guides](developer/providers/README.md) | Provider profiles, auth, client selection, wire conversion, streaming, retries, or tool-replay behavior changes |
| [LM Studio Anthropic-compatible guide](providers/LM_STUDIO_ANTHROPIC.md) | LM Studio's endpoint, authentication, or OpenHarness profile workflow changes |
| [LM Studio local manual test flow](testing/LM_STUDIO_LOCAL_MANUAL_TEST.md) | Local provider, terminal, or `ohmo` validation steps and pass criteria change |
| [Improvement backlog](developer/IMPROVEMENTS.md) | Evidence changes, an item is completed, or priorities are reconsidered |

`docs/autopilot/` is generated/published dashboard output. Edit `autopilot-dashboard/` or the
autopilot exporter rather than treating generated files as hand-maintained developer docs.
