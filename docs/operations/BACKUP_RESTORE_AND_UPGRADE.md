# Backup, restore, and upgrade

## Define the backup scope

Depending on enabled features, state spans:

- OpenHarness config, credential, data, and log roots;
- system keyring and external Claude/Codex/Copilot credential stores;
- each project's `.openharness` state and memory roots;
- ohmo workspace, gateway config, attachments, groups, memory, sessions, and logs;
- Git worktrees/branches/remotes and external PR/CI state;
- published dashboard/transcript artifacts.

Copying `~/.openharness` alone is not a complete backup.

## Consistent backup procedure

1. Record installed version and effective paths.
2. Stop ohmo gateway and cron scheduler.
3. Stop/inspect tasks, agents, bridge sessions, and autopilot runs.
4. Ensure no settings, memory, mailbox, session, or registry writer is active.
5. Copy state while preserving permissions and symlink semantics.
6. Back up keyring/external credentials with their owning tools.
7. Encrypt and access-control the backup; it can contain plaintext tokens and prompts.
8. Test restoration into isolated roots.

Atomic files prevent torn single-file reads but do not give a cross-directory snapshot.

## Restore procedure

1. Install the recorded version in a clean environment.
2. Restore to temporary `OPENHARNESS_*` roots and an explicit ohmo workspace.
3. Run read-only config/provider/session/cron/autopilot list/status commands.
4. Validate JSON/YAML/Markdown and permissions before starting services.
5. Test one disposable provider request and one isolated session restore.
6. Start scheduler/gateway in foreground first and inspect logs.
7. Move to managed background operation only after health is established.

Do not allow a newer binary to overwrite the only copy of older state before compatibility is
known.

## Upgrade procedure

Read changelog/release notes and [Compatibility](../COMPATIBILITY.md). Back up first. Upgrade the
package, verify entrypoints/dry-run, inspect migration commands, then test in this order: local
read-only, local model call, session resume, tools, gateway, cron, autopilot.

## Rollback

Stop writers, preserve post-upgrade state separately, reinstall the previous version, and restore
the pre-upgrade backup. External effects such as pushed commits, channel messages, model costs, or
PR comments are not rolled back by restoring local files.
