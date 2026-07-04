#!/usr/bin/env python3
"""Install, activate, list, or roll back source-built OpenHarness releases."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from local_release_common import (
    MANIFEST_NAME,
    activate_release,
    atomic_write_json,
    default_install_root,
    isolated_runtime_env,
    load_state,
    read_json,
    sha256_file,
    shell_path_command,
    validate_release_id,
    venv_command,
    venv_python,
)


ROOT = Path(__file__).resolve().parents[1]


def run(
    command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    """Run one visible installation command and stop on failure."""
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def wheel_from_manifest(manifest_path: Path) -> tuple[dict[str, Any], Path, str]:
    """Resolve and verify the exact wheel named by a build manifest."""
    manifest = read_json(manifest_path)
    if (
        manifest.get("schema_version") != 1
        or manifest.get("project") != "openharness-ai"
        or not manifest.get("release_id")
    ):
        raise ValueError(f"Unsupported or invalid build manifest: {manifest_path}")
    wheel_records = [
        item
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict) and item.get("kind") == "wheel"
    ]
    if len(wheel_records) != 1:
        raise ValueError("Build manifest must describe exactly one wheel")
    record = wheel_records[0]
    filename = str(record["filename"])
    if Path(filename).name != filename or not filename.endswith(".whl"):
        raise ValueError(f"Manifest wheel filename must be a local .whl basename: {filename}")
    wheel = (manifest_path.parent / filename).resolve()
    expected_hash = str(record["sha256"])
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ValueError(f"Manifest has an invalid wheel SHA-256: {expected_hash!r}")
    if not wheel.is_file():
        raise FileNotFoundError(f"Wheel from manifest does not exist: {wheel}")
    actual_hash = sha256_file(wheel)
    if actual_hash != expected_hash:
        raise ValueError(f"Wheel checksum mismatch: expected {expected_hash}, got {actual_hash}")
    return manifest, wheel, actual_hash


def install_frontend(release_dir: Path, *, offline: bool) -> None:
    """Install the packaged frontend's locked runtime/dev dependencies."""
    venv = release_dir / "venv"
    env = isolated_runtime_env(release_dir / "install-state")
    env["NPM_CONFIG_CACHE"] = str(release_dir.parents[1] / "cache" / "npm")
    result = subprocess.run(
        [
            str(venv_python(venv)),
            "-c",
            "from openharness.ui.react_launcher import get_frontend_dir; print(get_frontend_dir())",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    frontend = Path(result.stdout.strip())
    if not (frontend / "package-lock.json").is_file():
        raise RuntimeError(f"Installed wheel has no frontend package-lock.json: {frontend}")
    command = ["npm", "ci", "--no-audit", "--no-fund"]
    if offline:
        command.append("--offline")
    run(command, cwd=frontend, env=env)


def smoke_release(release_dir: Path) -> None:
    """Exercise installed entrypoints with disposable configuration/workspace paths."""
    venv = release_dir / "venv"
    env = isolated_runtime_env(release_dir / "smoke-state")
    run([str(venv_command(venv, "oh")), "--version"], env=env)
    run([str(venv_command(venv, "oh")), "--help"], env=env)
    run([str(venv_command(venv, "ohmo")), "--help"], env=env)


def install(args: argparse.Namespace) -> None:
    """Install a verified release transactionally, then activate its dedicated launchers."""
    root = args.root.expanduser().resolve()
    manifest, wheel, wheel_hash = wheel_from_manifest(args.manifest.expanduser().resolve())
    release_id = validate_release_id(str(manifest["release_id"]))
    release_dir = root / "releases" / release_id
    state = load_state(root)
    existing = state["releases"].get(release_id)
    if existing:
        if existing.get("wheel_sha256") != wheel_hash:
            raise ValueError(f"Release ID {release_id} is already installed with different bytes")
        if not args.skip_frontend and not existing.get("frontend_installed"):
            install_frontend(release_dir, offline=args.offline)
            smoke_release(release_dir)
            existing["frontend_installed"] = True
            existing["frontend_installed_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            atomic_write_json(release_dir / "release.json", existing)
        activate_release(root, state, release_id, record=True)
        print(f"Activated already-installed release {release_id}")
        print(shell_path_command(root / "bin", args.shell))
        return
    if release_dir.exists():
        raise FileExistsError(f"Untracked release directory already exists: {release_dir}")

    release_dir.mkdir(parents=True)
    try:
        venv = release_dir / "venv"
        run(["uv", "venv", "--python", sys.executable, str(venv)])
        command = ["uv", "pip", "install", "--python", str(venv_python(venv)), "--strict"]
        if args.offline:
            command.append("--offline")
        command.append(str(wheel))
        run(command)
        if not args.skip_frontend:
            install_frontend(release_dir, offline=args.offline)
        smoke_release(release_dir)
        release_metadata = {
            "version": manifest.get("version"),
            "wheel_sha256": wheel_hash,
            "source_commit": manifest.get("source", {}).get("commit"),
            "installed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "frontend_installed": not args.skip_frontend,
        }
        atomic_write_json(release_dir / "release.json", release_metadata)
        state["releases"][release_id] = release_metadata
        activate_release(root, state, release_id, record=True)
    except BaseException:
        shutil.rmtree(release_dir, ignore_errors=True)
        raise

    print(f"Installed and activated {release_id}")
    print("Use this release in the current shell only:")
    print(shell_path_command(root / "bin", args.shell))


def list_releases(root: Path) -> None:
    """Print releases known to installer-owned state."""
    state = load_state(root.expanduser().resolve())
    if not state["releases"]:
        print("No local releases installed.")
        return
    for release_id, metadata in state["releases"].items():
        marker = "*" if release_id == state.get("active") else " "
        print(f"{marker} {release_id}  installed={metadata.get('installed_at_utc', 'unknown')}")


def activate(root: Path, release_id: str) -> None:
    """Activate an already-installed release."""
    resolved = root.expanduser().resolve()
    state = load_state(resolved)
    activate_release(resolved, state, release_id, record=True)
    print(f"Activated {release_id}")


def rollback(root: Path) -> None:
    """Return launchers to the most recently active installed release."""
    resolved = root.expanduser().resolve()
    state = load_state(resolved)
    releases = state["releases"]
    target = None
    while state["history"] and target is None:
        candidate = state["history"].pop()
        if candidate in releases and candidate != state.get("active"):
            target = candidate
    if target is None:
        raise RuntimeError("No previous installed release is available for rollback")
    activate_release(resolved, state, target, record=False)
    print(f"Rolled back launchers to {target}")
    print("Configuration and persisted data were not changed.")


def build_parser() -> argparse.ArgumentParser:
    """Build the local release management command tree."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_install_root())
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install", help="install and activate a build manifest")
    install_parser.add_argument(
        "--manifest", type=Path, default=ROOT / ".local-release" / "dist" / MANIFEST_NAME
    )
    install_parser.add_argument("--offline", action="store_true")
    install_parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="skip npm ci; oh/ohmo TUI startup will install dependencies on first use",
    )
    default_shell = "powershell" if os.name == "nt" else "posix"
    install_parser.add_argument(
        "--shell", choices=("posix", "powershell", "cmd"), default=default_shell
    )

    subparsers.add_parser("list", help="list installed local releases")
    activate_parser = subparsers.add_parser("activate", help="activate an installed release")
    activate_parser.add_argument("release_id")
    subparsers.add_parser("rollback", help="activate the previous release")
    env_parser = subparsers.add_parser("env", help="print a current-shell PATH command")
    env_parser.add_argument(
        "--shell", choices=("posix", "powershell", "cmd"), default=default_shell
    )
    return parser


def main() -> int:
    """Dispatch one local release management operation."""
    args = build_parser().parse_args()
    if args.command == "install":
        install(args)
    elif args.command == "list":
        list_releases(args.root)
    elif args.command == "activate":
        activate(args.root, args.release_id)
    elif args.command == "rollback":
        rollback(args.root)
    elif args.command == "env":
        print(shell_path_command(args.root.expanduser().resolve() / "bin", args.shell))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
