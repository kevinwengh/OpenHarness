# ADR-0003: Project skills enabled, project plugin code opt-in

## Status

Accepted; owned by settings, skill discovery, and plugin loading.

## Context

Repositories need to provide project instructions, but opening an untrusted checkout must not
silently import arbitrary Python plugin tools or run plugin hooks.

## Decision

Discover configured project skill roots by default (`allow_project_skills=true`) because they are
instruction content. Keep project plugin execution disabled unless `allow_project_plugins=true`.
User-installed/enabled plugins remain trusted user code.

## Alternatives

- disable all project extensions: safer but harms project-specific guidance;
- enable all project plugins: rejected due import-time arbitrary code execution;
- sandbox every extension: not implemented and does not cover all Python/host integration needs.

## Consequences

Projects can teach workflows without automatic Python import. Skills can still steer the model and
must be treated as prompt-injection input. Explicit plugin enablement expands the trusted computing
base to code, hooks, MCP settings, and commands.

## Revisit when

Plugin discovery can present declared capabilities and execute in a defensible isolation boundary,
or when project-skill prompt injection requires a stronger default.
