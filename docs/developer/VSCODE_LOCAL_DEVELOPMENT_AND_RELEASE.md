# VS Code development, debugging, and local source releases

This guide is the repeatable path for developing `oh` and `ohmo` in VS Code, debugging the
Python/TypeScript process boundary, and installing a source build on the same host without a
GitHub or package-index release. The helper scripts deliberately keep installation files separate
from application settings and do not overwrite an existing editor setup, command installation,
shell profile, `~/.openharness`, or `~/.ohmo`.

## What is isolated, and what is not

There are three distinct kinds of state. Keeping them separate prevents most confusing local
development failures.

| State | Default location in this workflow | Safety behavior |
| --- | --- | --- |
| Source dependencies | `.venv/` and `frontend/terminal/node_modules/` | Managed by `uv` and npm; ignored by Git |
| Disposable debug/test state | `.local-dev/` | Used only by configurations labeled “isolated”; ignored by Git |
| Built artifacts | `.local-release/dist/` | Contains the wheel, sdist, and checksum manifest; ignored by Git |
| Installed local releases | `~/.local/share/openharness/source-releases/` on POSIX | Versioned virtual environments and dedicated launchers; not app configuration |
| Normal app settings/data | `~/.openharness/` and `~/.ohmo/` unless overridden | Never written by the setup/build/install scripts |

On Windows, the default local-release root is
`%LOCALAPPDATA%\OpenHarness\source-releases`. `XDG_DATA_HOME` changes the POSIX install root in
the standard way.

The installation is isolated, but running an activated `oh` normally still reads your existing
OpenHarness configuration. This is intentional: it lets a local binary use your established
providers and preferences without copying or replacing them. Use the isolated environment in
[Run an installed release against disposable state](#run-an-installed-release-against-disposable-state)
when you do not want the process to read normal state either.

The local-release root also owns a shared npm download cache used when installing packaged terminal
dependencies. This avoids writing npm state into the OpenHarness configuration directories and
allows subsequent releases to reuse downloads.

## Prerequisites

Install these commands on the local host:

- Python 3.10 or newer;
- `uv`;
- Node.js 20 and npm;
- Git;
- VS Code with the recommended Python, Pylance, Ruff, and ESLint extensions.

From the repository root, confirm the toolchain:

```bash
python3 --version
uv --version
node --version
npm --version
git status --short --branch
```

## One-time source and VS Code setup

Run the checked-in setup helper:

```bash
uv run python scripts/setup_vscode.py --install-deps
```

It runs `uv sync --extra dev` and `npm ci`, then copies the templates from `scripts/vscode/` into
the ignored `.vscode/` directory. If `settings.json`, `launch.json`, `tasks.json`, or
`extensions.json` already exists there, the script reports and preserves that file byte for byte.
To preview the templates before copying them, inspect `scripts/vscode/` directly. To stage them in
another directory for a manual merge:

```bash
uv run python scripts/setup_vscode.py --target /tmp/openharness-vscode
```

Open the repository directory in VS Code. Select the interpreter at `.venv/bin/python` on POSIX
or `.venv\Scripts\python.exe` on Windows. The templates remain personal/ignored files; changes to
them are not committed accidentally.

If you already maintain VS Code files, copy only the configurations or tasks you need from the
templates. The setup helper has no force/overwrite mode by design.

## How `uv run oh` starts the terminal

The source launch is a small process tree, not one Python function running the whole UI:

```text
uv run oh
  -> console script: openharness.cli:app
  -> Python launcher: openharness.ui.react_launcher.launch_react_tui
  -> Node/tsx: frontend/terminal/src/index.tsx
  -> child Python: python -m openharness --backend-only ...
  -> runtime composition and prompt/tool loop
```

The first Python process resolves settings and starts the React/Ink terminal. The TypeScript
frontend then starts a JSON-lines backend using the command passed in
`OPENHARNESS_FRONTEND_CONFIG`. The backend composes the runtime in
`src/openharness/ui/runtime.py`; prompts and tools flow through
`src/openharness/engine/query.py`. See the
[interactive frontend/backend flow](flows/INTERACTIVE_OH_FRONTEND_BACKEND_E2E.md) for the full
protocol and shutdown sequence.

This process split determines where a breakpoint must be placed:

- CLI dispatch or frontend launch: `src/openharness/cli.py` and
  `src/openharness/ui/react_launcher.py`;
- backend protocol: `src/openharness/ui/backend_host.py`;
- runtime construction: `src/openharness/ui/runtime.py`;
- model/tool loop: `src/openharness/engine/query.py`;
- React input/rendering: `frontend/terminal/src/index.tsx` and its imported hooks/components;
- ohmo composition: `ohmo/cli.py`, `ohmo/runtime.py`, and `ohmo/workspace.py`.

## Included VS Code launch configurations

Open **Run and Debug**, choose a configuration, and press **F5**.

### `oh: dry-run (isolated state)`

This is the safest first Python debugging target. It executes `python -m openharness --dry-run`
through the selected interpreter, points configuration at `.local-dev/openharness`, and makes no
model call. Use it for CLI parsing, settings precedence, provider resolution, runtime inspection,
and startup failures.

### `oh: prompt (normal user state)`

VS Code asks for a prompt and runs a real source-checkout request. It intentionally uses normal
user configuration so existing provider credentials can be resolved. A model call may cost money,
and approved tools can change the working tree. Use a harmless prompt and an appropriate
permission mode while debugging.

### `oh: TUI (normal user state)`

This starts the actual React terminal via Python. The configuration enables subprocess debugging,
which allows `debugpy` to follow the Python backend spawned after Node starts. Terminal raw-mode
behavior is most reliable in the integrated terminal rather than the Debug Console.

If a child-process breakpoint does not bind on your VS Code/debugpy version, debug the same code
without the frontend by adding `--backend-only` only when you are prepared to send protocol JSON,
or place the breakpoint in a narrow pytest test. The frontend/backend lifecycle guide includes
protocol examples.

### `terminal frontend: Node + Python backend`

Use this configuration for TypeScript breakpoints. It runs `npm run start` in
`frontend/terminal/`, provides a backend command through `OPENHARNESS_FRONTEND_CONFIG`, and keeps
both frontend and backend state under `.local-dev/`. The Node debugger does not automatically
debug the Python child; use one of the Python configurations for Python breakpoints.

### `ohmo: TUI (isolated workspace)`

Initialize the disposable workspace once using **Tasks: Run Task** and
`ohmo: initialize isolated workspace`, or run:

```bash
uv run ohmo init --no-interactive --workspace .local-dev/ohmo
```

Then start the ohmo launch configuration. It keeps the ohmo workspace and OpenHarness settings
inside `.local-dev/`. To debug against your real personal workspace, make a private copy of the
configuration with the `--workspace` argument and isolated environment removed.

## Normal edit, run, and test loop

For a quick source run:

```bash
uv run oh --dry-run --output-format json
uv run oh "Explain the current git diff"
uv run ohmo --help
```

The VS Code tasks expose the same repository checks. From a shell, use the narrowest relevant test
while iterating, then the baseline before installing a release:

```bash
uv run pytest -q tests/test_ui
uv run ruff check src tests scripts
uv run python scripts/check_docs.py
OPENHARNESS_CONFIG_DIR="$PWD/.local-dev/test-state/openharness" uv run pytest -q
(cd frontend/terminal && npm ci && npx tsc --noEmit)
```

Only `OPENHARNESS_CONFIG_DIR` is set for the full test suite: the data and log directories then
remain children of that isolated configuration root, which preserves the path compatibility
contract tested by the suite. Real provider/model calls are not part of these offline tests.

## Build a local source release

The full builder runs Ruff, documentation validation, the Python suite with isolated state,
frontend dependency installation, and TypeScript validation. It then builds and inspects one
wheel and one source distribution:

```bash
uv run python scripts/build_local_release.py
```

Outputs are written to `.local-release/dist/`:

- the `openharness_ai-<version>-*.whl` wheel;
- the matching source distribution;
- `openharness-local-release.json`, containing the release ID, source commit/dirty state,
  artifact filenames, sizes, and SHA-256 checksums.

Wheel inspection fails the build unless all four console scripts and the packaged terminal
frontend source, `package.json`, and `package-lock.json` are present. A dirty checkout receives a
timestamped release ID so it cannot silently masquerade as the clean commit build.

For a fast packaging iteration after checks have already passed:

```bash
uv run python scripts/build_local_release.py --quick
```

`--quick` still builds and inspects the artifact but skips tests, lint, docs, dependency
reinstallation, and TypeScript. Do not treat it as a release-quality validation.

To keep artifacts elsewhere, pass `--output-dir /absolute/path`. The builder does not delete
unrelated files in that directory.

## Install without replacing an existing `oh`

Install the exact wheel named and checksummed by the manifest:

```bash
uv run python scripts/install_local_release.py install
```

The installer performs these steps before activation:

1. validates the manifest and wheel SHA-256;
2. creates a new virtual environment under the versioned local-release root;
3. installs the wheel with `uv pip install --strict`;
4. runs `npm ci` against the frontend packaged in that virtual environment;
5. runs `oh --version`, `oh --help`, and `ohmo --help` with disposable state;
6. atomically points four dedicated launchers at the successful release.

If any step fails, the incomplete release directory is removed and the active launchers are left
alone. The installer refuses to replace any launcher in its own `bin` directory that it did not
create. It never writes `~/.local/bin`, replaces another virtual environment, or edits a shell
profile.

The new launchers are not automatically placed on `PATH`. The installer prints a command for the
current shell. You can print it again and apply it on POSIX:

```bash
eval "$(uv run python scripts/install_local_release.py env --shell posix)"
command -v oh
oh --version
```

Because this only changes the current shell, open a new terminal to return to the previously
installed `oh`. If you intentionally want local releases to win in every shell, add the printed
directory to your profile manually after reviewing it; the script will not make that decision.

PowerShell and Command Prompt equivalents are:

```powershell
uv run python scripts/install_local_release.py env --shell powershell
```

```bat
uv run python scripts/install_local_release.py env --shell cmd
```

Copy and execute the printed command in the current terminal.

## Run an installed release against disposable state

To prove that the installed release does not depend on normal settings, use a temporary config and
ohmo workspace:

```bash
export OPENHARNESS_CONFIG_DIR="$PWD/.local-dev/installed-smoke/openharness"
export OHMO_WORKSPACE="$PWD/.local-dev/installed-smoke/ohmo"
oh --dry-run --output-format json
ohmo init --no-interactive
ohmo --help
```

Unset the variables to return to normal settings:

```bash
unset OPENHARNESS_CONFIG_DIR OHMO_WORKSPACE
```

Do not set these variables when your goal is to use the new local binary with existing provider
profiles and personal memory.

## List, switch, and roll back releases

Each source build has its own virtual environment. Manage only the dedicated launchers with:

```bash
uv run python scripts/install_local_release.py list
uv run python scripts/install_local_release.py activate RELEASE_ID
uv run python scripts/install_local_release.py rollback
```

`rollback` selects the most recently active installed release. It changes executable launchers
only; it does not downgrade or restore settings, sessions, memory, schemas, project files, or any
external side effects caused while using a newer release. Review migrations and persisted-format
changes before using old code with newer state.

For an alternate install root, global options must precede the subcommand:

```bash
uv run python scripts/install_local_release.py --root /tmp/oh-releases install
uv run python scripts/install_local_release.py --root /tmp/oh-releases list
```

This is useful for a completely disposable end-to-end installation test.

## Offline and no-GitHub behavior

The builder and installer never clone from or publish to GitHub. A normal first run can still
contact Python and npm registries to obtain dependencies. After the required artifacts are in the
local uv/npm caches, request offline installation:

```bash
uv run python scripts/install_local_release.py install --offline
```

Offline mode passes the corresponding offline option to uv and npm. It fails rather than fetching
if either cache is incomplete. `--skip-frontend` skips `npm ci`; the first later TUI launch will
attempt its normal dependency installation, so this option is not a fully offline TUI install.
Re-running `install` without `--skip-frontend` completes the locked frontend installation for a
previously installed matching release rather than rebuilding its Python environment.

## Troubleshooting

### VS Code imports do not resolve

Select the repository `.venv` interpreter, run `uv sync --extra dev`, and reload the VS Code
window. The template adds both `src` and the repository root to Python analysis paths because core
uses the `src` layout while ohmo is a top-level package.

### Python breakpoints work before Node starts but not in the backend

Confirm `subProcess` remains enabled. Put the breakpoint in
`src/openharness/ui/backend_host.py` after backend startup, or reproduce the backend behavior with
a focused test. Use the Node launch configuration separately for TypeScript breakpoints.

### The TUI starts an npm install unexpectedly

Source runs require `frontend/terminal/node_modules`. Installed runs require the same directory
inside the selected release's virtual environment. Re-run source `npm ci`, or reinstall the local
release without `--skip-frontend`.

### `oh` still resolves to another installation

Inspect command resolution and print the local PATH command:

```bash
command -v -a oh
uv run python scripts/install_local_release.py env --shell posix
```

Apply it in the same terminal. Shell command hashing may require `hash -r` after changing `PATH`.

### An install reports a non-managed launcher collision

The installer stops to protect the existing file. Inspect the reported path. Move or rename it
only if you know why it is inside the dedicated local-release `bin` directory, then retry. Do not
add a force replacement: collision refusal is the ownership boundary.

### A build works but an older release behaves differently with current state

Executable rollback is not data rollback. Reproduce with `.local-dev/` state first. If a change
introduced a persisted-format migration, follow that subsystem's compatibility/backup guidance
before pointing old code at normal state.

## Script ownership and validation

The workflow is implemented by:

- `scripts/setup_vscode.py` and `scripts/vscode/` for non-overwriting editor setup;
- `scripts/build_local_release.py` for validation, build, inspection, and the checksum manifest;
- `scripts/install_local_release.py` for install, smoke test, activation, listing, and rollback;
- `scripts/local_release_common.py` for path, hashing, atomic-state, and launcher ownership rules;
- `tests/test_install/test_local_release_scripts.py` for the safety-critical local behavior.

When changing these files, run their focused tests, Ruff, the documentation checker, and an actual
build/install into a temporary root. Packaging changes also require the terminal TypeScript check.
