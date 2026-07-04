# Security policy

OpenHarness executes model-selected tools, loads local extensions, connects to external model and
channel services, and persists conversations and credentials. Security reports are welcome and
should be handled privately until a fix and disclosure plan are ready.

## Supported versions

The project does not yet publish a formal long-term-support matrix. Security fixes target the
latest released version and the current `main` branch. Older releases may require upgrading rather
than receiving a backport. Release versions are recorded in `CHANGELOG.md` and `pyproject.toml`.

## Report a vulnerability

Do not open a public issue for an unpatched vulnerability or include live credentials, private
prompts, session data, channel identifiers, or exploit payloads in public artifacts.

Use GitHub's private vulnerability reporting feature for this repository when it is available. If
private reporting is unavailable, contact the repository maintainers through a private channel
listed on the repository owner profile and request a secure reporting path. Include:

- affected version or commit;
- operating system and execution mode (`oh`, `ohmo`, gateway, cron, or autopilot);
- required configuration and trust assumptions;
- reproducible steps using synthetic secrets and disposable data;
- impact, including whether confidentiality, integrity, or availability is affected;
- any known mitigation or evidence that exploitation occurred.

Maintainers should acknowledge a complete report, reproduce it in an isolated environment, agree
on disclosure timing, and avoid requesting the reporter's real credentials or private workspace.
Response-time commitments are not currently formalized.

## Security boundaries

OpenHarness does not treat model output, project content, downloaded content, channel messages, or
MCP responses as trusted. Important enforced or configurable boundaries include:

- built-in sensitive-path denial in `src/openharness/permissions/checker.py`;
- tool input validation and permission evaluation in `src/openharness/engine/query.py`;
- project plugins disabled unless `allow_project_plugins` is enabled;
- channel `allow_from` policies and gateway command restrictions;
- optional Docker sandbox routing for supported tools;
- credential redaction in configuration displays;
- path and network validation in sandbox and web helpers.

These controls reduce risk but do not make full-auto execution, plugins, hooks, MCP servers,
autopilot, or remote channels safe in an untrusted environment. Read the
[threat model](docs/security/THREAT_MODEL.md) and
[data-handling guide](docs/security/DATA_HANDLING.md) before exposing a gateway or enabling
autonomous mutation.

## Out of scope and non-guarantees

- Base64, including bridge work-secret encoding, is not encryption.
- The file credential fallback is plaintext JSON protected by filesystem permissions.
- Docker sandboxing is not a universal wrapper around every extension or network operation.
- Full-auto removes interactive confirmation for many tools; it is not rollback or isolation.
- A trusted plugin or hook executes with the current user's authority unless it creates its own
  isolation boundary.
- External model, channel, MCP, and web services receive data required by the request and apply
  their own security and retention policies.

## Safe report handling

Use temporary configuration roots (`OPENHARNESS_CONFIG_DIR`, `OPENHARNESS_DATA_DIR`, and
`OPENHARNESS_LOGS_DIR`) for reproduction. Remove secrets from logs and screenshots. Do not commit
`~/.openharness`, `~/.ohmo`, session snapshots, attachments, cron state, task output, bridge logs,
or generated credentials.
