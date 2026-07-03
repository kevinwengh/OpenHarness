"""Launch the default React terminal frontend.

Integration: This module participates in runtime composition and adapters for CLI, React,
Textual, headless, and ohmo callers.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve startup/readiness, protocol ordering, callback ownership, interruption,
persistence, and resource cleanup.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path


def _resolve_theme() -> str:
    """Read the persisted theme for frontend bootstrap, falling back safely.

    The launcher runs before the backend protocol is available, so theme loading
    cannot report through the TUI and must not prevent startup. Keep the fallback
    aligned with the TypeScript theme registry.

    Integration: Called by ``launch_react_tui`` and collaborates with ``load_settings``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    try:
        from openharness.config.settings import load_settings
        return load_settings().theme or "default"
    except Exception:
        return "default"


def _resolve_npm() -> str:
    """Resolve the platform npm launcher used for install and fallback execution.

    Returning a bare name preserves normal PATH error reporting. Keep Windows
    command-wrapper behavior in mind when changing subprocess invocation.

    Integration: Called by ``launch_ohmo_react_tui``, ``_resolve_tsx`` and collaborates with
    ``shutil.which``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return shutil.which("npm") or "npm"


def _resolve_tsx(frontend_dir: Path) -> tuple[str, ...]:
    """Resolve the tsx command to invoke directly, bypassing ``npm exec``.

    On Windows / WSL the ``npm exec -- tsx`` wrapper chain often spawns
    intermediate ``cmd.exe`` / shell processes that break TTY stdin
    inheritance.  Calling the ``tsx`` binary directly preserves the TTY so
    that Ink's ``useInput`` (which requires raw-mode stdin) keeps working.

    Returns a tuple of command parts, e.g. ``("path/to/tsx",)`` or
    ``("npm", "exec", "--", "tsx")`` as last-resort fallback.
    The caller expands this tuple directly into ``create_subprocess_exec``;
    preserve argument boundaries and avoid shell interpolation.

    Integration: Called by ``launch_ohmo_react_tui``, ``launch_react_tui`` and collaborates with
    ``shutil.which``, ``candidate.exists``, ``_resolve_npm``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    # 1. Prefer the locally-installed binary
    bin_dir = frontend_dir / "node_modules" / ".bin"
    if sys.platform == "win32":
        for name in ("tsx.cmd", "tsx.ps1", "tsx"):
            candidate = bin_dir / name
            if candidate.exists():
                return (str(candidate),)
    else:
        candidate = bin_dir / "tsx"
        if candidate.exists():
            return (str(candidate),)

    # 2. Fall back to a globally-installed tsx
    global_tsx = shutil.which("tsx")
    if global_tsx:
        return (global_tsx,)

    # 3. Last resort — go through npm exec (may break TTY on Windows/WSL)
    return (_resolve_npm(), "exec", "--", "tsx")


def get_frontend_dir() -> Path:
    """Return the React terminal frontend directory.

    Checks in order:
    1. Bundled inside the installed package (pip install)
    2. Development repo layout (source checkout)

    Packaging and source-checkout tests depend on this order. The fallback path
    intentionally lets ``launch_react_tui`` produce one clear missing-file error.

    Integration: Called by ``launch_ohmo_react_tui``, ``launch_react_tui`` and collaborates with
    ``exists``, ``resolve``, ``Path``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    # 1. Bundled inside package: openharness/_frontend/
    pkg_frontend = Path(__file__).resolve().parent.parent / "_frontend"
    if (pkg_frontend / "package.json").exists():
        return pkg_frontend

    # 2. Development repo: <repo>/frontend/terminal/
    repo_root = Path(__file__).resolve().parents[3]
    dev_frontend = repo_root / "frontend" / "terminal"
    if (dev_frontend / "package.json").exists():
        return dev_frontend

    # Fallback to package path (will error with clear message)
    return pkg_frontend


def build_backend_command(
    *,
    cwd: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    effort: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_format: str | None = None,
    permission_mode: str | None = None,
) -> list[str]:
    """Build the argv the React process uses to spawn its Python backend.

    The command re-enters the current interpreter with ``--backend-only`` and
    forwards explicit CLI overrides. Keep values as separate argv elements,
    preserve the recursion guard, and never log the resulting list unredacted
    because it may contain an API key.

    Integration: Called by ``launch_react_tui`` and collaborates with ``command.extend``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    command = [sys.executable, "-m", "openharness", "--backend-only"]
    if cwd:
        command.extend(["--cwd", cwd])
    if model:
        command.extend(["--model", model])
    if max_turns is not None:
        command.extend(["--max-turns", str(max_turns)])
    if effort:
        command.extend(["--effort", effort])
    if base_url:
        command.extend(["--base-url", base_url])
    if system_prompt:
        command.extend(["--system-prompt", system_prompt])
    if api_key:
        command.extend(["--api-key", api_key])
    if api_format:
        command.extend(["--api-format", api_format])
    if permission_mode:
        command.extend(["--permission-mode", permission_mode])
    return command


async def launch_react_tui(
    *,
    prompt: str | None = None,
    cwd: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    effort: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_format: str | None = None,
    permission_mode: str | None = None,
) -> int:
    """Start the TypeScript terminal frontend and await its process exit code.

    This coroutine runs in the initial Python CLI event loop. It may install
    missing dependencies, exports bootstrap configuration through one environment
    variable, and attaches child stdio directly to the terminal. Preserve
    subprocess argument safety, cancellation/exit propagation, packaged and
    development layouts, and the frontend-to-backend option contract.
    """
    frontend_dir = get_frontend_dir()
    package_json = frontend_dir / "package.json"
    if not package_json.exists():
        raise RuntimeError(f"React terminal frontend is missing: {package_json}")

    npm = _resolve_npm()

    if not (frontend_dir / "node_modules").exists():
        install = await asyncio.create_subprocess_exec(
            npm,
            "install",
            "--no-fund",
            "--no-audit",
            cwd=str(frontend_dir),
        )
        if await install.wait() != 0:
            raise RuntimeError("Failed to install React terminal frontend dependencies")

    env = os.environ.copy()
    env["OPENHARNESS_FRONTEND_CONFIG"] = json.dumps(
        {
            "backend_command": build_backend_command(
                cwd=cwd or str(Path.cwd()),
                model=model,
                max_turns=max_turns,
                effort=effort,
                base_url=base_url,
                system_prompt=system_prompt,
                api_key=api_key,
                api_format=api_format,
                permission_mode=permission_mode,
            ),
            "initial_prompt": prompt,
            "theme": _resolve_theme(),
        }
    )
    tsx_cmd = _resolve_tsx(frontend_dir)
    process = await asyncio.create_subprocess_exec(
        *tsx_cmd,
        "src/index.tsx",
        cwd=str(frontend_dir),
        env=env,
        stdin=None,
        stdout=None,
        stderr=None,
    )
    return await process.wait()


__all__ = ["build_backend_command", "get_frontend_dir", "launch_react_tui"]
