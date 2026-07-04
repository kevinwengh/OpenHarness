# ADR-0005: Separate reusable OpenHarness core from ohmo

## Status

Accepted with known boundary debt. See [Product boundaries](../PRODUCT_BOUNDARIES.md).

## Context

The model/tool runtime supports coding-agent and embedded hosts. ohmo adds personal identity, memory,
workspace, long-lived channels, routing, groups, notifications, and runtime pooling.

## Decision

Reusable contracts and runtime behavior live under `src/openharness`; personal workspace and gateway
policy live under `ohmo`. ohmo composes core by injecting session/memory roots, prompts, plugins,
tools, and channel behavior.

## Alternatives

- make ohmo a core mode: couples reusable runtime to one product/deployment;
- fork the engine: duplicates provider, permission, tool, and persistence behavior;
- separate repositories immediately: rejected while interfaces are still evolving together.

## Consequences

One engine serves multiple products while ohmo can specialize state and channels. Current optional
reverse imports from core into ohmo for attachments, group lookup, and cron notification violate the
desired direction and should be replaced by core-owned protocols/adapters.

## Revisit when

All reverse dependencies are removed and release/version boundaries justify separate packaging or
repositories.
