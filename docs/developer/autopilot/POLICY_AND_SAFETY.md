# Autopilot policy and safety

Autopilot initializes three YAML policies. Operators may edit them; code reads them through
`RepoAutopilotStore.load_policies()` and `_read_yaml()`.

## Autopilot policy

Default sections in `_DEFAULT_AUTOPILOT_POLICY`:

| Section | Controls |
| --- | --- |
| `intake` | visible-candidate bound and source-ref/fingerprint deduplication |
| `decision` | declared human-gate and small-step preferences; currently prompt/policy context rather than merge enforcement |
| `execution` | model, turns, permission mode, host mode, worktree, branch, attempts |
| `github` | comments, branch prefix, CI timing, no-check grace, label-gated auto-merge |
| `repair` | max rounds is enforced; retryable/terminal reason lists are currently descriptive |

The default `permission_mode` is `full_auto` and `use_worktree` is true. The worktree confines Git
working-copy mutation, not network calls, credentials, subprocesses, GitHub comments, pushes, or
provider data.

`_max_attempts()` enforces the larger of `execution.max_attempts` and `repair.max_rounds + 1`.
Current code does not consult `repair.retry_on` or `repair.stop_on` before deciding its hard-coded
retry paths. Treat those lists as intended policy vocabulary, not active controls.

## Verification policy

The default runs Python tests, Ruff, and frontend TypeScript checking when relevant files are
present. `_parse_verification_entry()` treats a plain string as argv and rejects shell metacharacters.
To request shell semantics, the YAML entry must be a mapping with `shell: true`.

```yaml
commands:
  - uv run pytest -q
  - command: cd frontend/terminal && npm ci && npx tsc --noEmit
    shell: true
```

Shell opt-in is an execution-authority decision. Issue/PR text must never be interpolated into a
verification command. `_run_verification_steps()` records stdout/stderr/return code; those outputs
may contain private data and flow into reports/model repair prompts.

## Release policy

The file declares `merge_requires_human`, `release_requires_human`, and
`auto_revert_on_failed_verification`, but the current service does not enforce those fields.
`_automerge_eligible()` reads only `autopilot_policy.yaml`'s GitHub auto-merge mode/required label
plus PR draft state. In `label_gated` mode, a matching label can therefore allow automatic squash
merge even while `merge_requires_human: true` remains in `release_policy.yaml`.

Until enforcement is implemented and tested, use `autopilot.github.auto_merge.mode: pr_only` to
prevent service-driven merging. Do not rely on release-policy human-gate fields as a safety control.

## Untrusted inputs

- issue/PR titles, bodies, labels, comments, branches, and CI output;
- local candidate files;
- model response and generated files;
- repository scripts invoked by verification;
- Git hooks and package installation side effects.

Prompts should delimit candidate text as data and restate scope/verification. Policy files belong to
the trusted repository/operator boundary.

Malformed or non-mapping YAML is silently replaced with built-in defaults by `_read_yaml()`. Validate
all three files before operation; a parse error is not currently a fail-closed condition.

## Safe policy changes

1. Change one policy dimension at a time.
2. Add/adjust tests using temporary repos and mocked `gh`.
3. Validate malformed/missing YAML and unavailable commands.
4. Preserve enforced attempts/repair bounds, and add tests before treating declared gate/reason
   fields as active controls.
5. Use a disposable repository before enabling scheduled ticks or auto-merge.
6. Never put credentials into policy files or command strings.
