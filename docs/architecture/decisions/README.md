# Architecture decision records

These ADRs record current implemented decisions and their consequences. They do not replace the
source-backed architecture guides; each ADR links to the detailed owner. A future change should mark
an ADR superseded rather than rewriting history to make the old decision disappear.

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-provider-neutral-engine.md) | Accepted | provider-neutral engine and normalized streams |
| [0002](0002-local-file-persistence.md) | Accepted | local file persistence with atomic replacement/locks |
| [0003](0003-project-extension-trust.md) | Accepted | project skills enabled, project plugin code opt-in |
| [0004](0004-terminal-pipe-protocol.md) | Accepted | local parent/child pipe protocol for React terminal |
| [0005](0005-core-ohmo-separation.md) | Accepted with debt | reusable core and application-specific ohmo |
| [0006](0006-runtime-per-conversation.md) | Accepted | one cached runtime bundle per gateway session key |
| [0007](0007-concurrent-sibling-tools.md) | Accepted | concurrent sibling tool execution with ordered replay |

## ADR template

Every record should include status, context, decision, alternatives, consequences, evidence, and
revisit triggers. Architecture changes also update `docs/ARCHITECTURE.md` and the owning decision
guide.
