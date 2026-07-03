"""Namespace for trusted plugins distributed with OpenHarness.

Bundled code is distinct from dynamically discovered user and project plugins;
do not use this package to bypass plugin manifests, enable untrusted project code,
or create resources during import.

Integration: This module participates in manifest-driven discovery of optional skills, commands,
agents, tools, hooks, and MCP servers.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve project-plugin opt-in trust, import isolation, precedence, namespacing,
and actionable load failures.
"""
