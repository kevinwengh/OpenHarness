# Release playbook

There is no checked-in automated package-publication workflow today. This playbook defines a safe
manual/dry-run process; it does not authorize publication or replace maintainer approval.

For a checksummed, versioned install on the current host without publication or GitHub, use the
[VS Code and local source release guide](developer/VSCODE_LOCAL_DEVELOPMENT_AND_RELEASE.md). That
workflow keeps its launchers separate from an existing installation and does not edit application
configuration.

## Release inputs

Confirm the intended version and supported Python/Node matrix. Version-sensitive locations include:

- `pyproject.toml`;
- `src/openharness/cli.py::__version__`;
- `ohmo/__init__.py::__version__`;
- user-agent version constants where they intentionally reflect package version;
- `CHANGELOG.md`, release notes, README, and installation examples.

Current source contains historical fallback/user-agent literals in command, Copilot, and web-fetch
code. Before release, decide whether they should derive from package metadata and add a consistency
check rather than updating them manually forever.

## Pre-release checklist

1. Start from a clean branch and review all `Unreleased` entries.
2. Confirm every user-visible change has documentation and migration notes.
3. Search for stale version/test/tool counts and unsupported compatibility claims.
4. Run the repository CI baseline:

   ```bash
   uv sync --extra dev
   uv run ruff check src tests scripts
   uv run python scripts/check_docs.py
   uv run pytest -q
   cd frontend/terminal && npm ci && npx tsc --noEmit
   ```

5. Build the dashboard when its source/export changed.
6. Render and visually inspect changed SVGs; review Mermaid diagrams and prose semantics that the
   structural documentation check does not parse.
7. Use live/provider/channel/Docker evaluations only when explicitly required and with disposable
   credentials/state.

## Build and inspect artifacts

Use the repository's Hatchling/uv toolchain in an isolated environment:

```bash
uv build
```

Inspect both wheel and source distribution before uploading:

- correct package/version metadata;
- `openharness`, `oh`, `openh`, and `ohmo` console scripts;
- `openharness/_frontend` wheel package populated from `frontend/terminal` by Hatchling;
- bundled skills/plugins and required non-Python files;
- no credentials, sessions, caches, logs, worktrees, `.openharness`, `.ohmo`, or generated local
  state;
- license, README, and dependency metadata.

Install the wheel into a clean environment and smoke test:

```bash
oh --version
oh --help
ohmo --help
oh --dry-run --output-format json
```

Dry-run proves packaging/config composition, not provider connectivity.

## Publish and tag

Publication requires maintainer approval and least-privilege credentials. Prefer a trusted
publisher workflow when one is introduced. For a manual release:

1. upload to a test index or otherwise validate the exact artifacts;
2. publish those immutable bytes to the production index;
3. create an annotated/signed tag matching the package version;
4. publish release notes and checksums/artifact links;
5. verify a fresh installation from the public index;
6. monitor issue reports and installation telemetry available to maintainers.

Never rebuild different bytes under the same version.

## Rollback and incident response

Python packages are generally immutable. If a release is unsafe, yank it with a clear reason,
publish a fixed version, update installation guidance, and preserve the bad artifact for forensic
comparison. If credentials or private files were included, rotate/revoke first and follow the
security-report process; deletion from the latest release does not erase mirrors or caches.

## Future automation

A release workflow should verify version consistency, build wheel/sdist, inspect contents, run
entrypoint smoke tests, attest provenance, and use an approval-gated trusted publisher. Keep
publication separate from ordinary pull-request CI.
