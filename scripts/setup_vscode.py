#!/usr/bin/env python3
"""Create missing repository-local VS Code files without overwriting personal settings."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "scripts" / "vscode"
TEMPLATE_NAMES = ("settings.json", "launch.json", "tasks.json", "extensions.json")


def copy_missing_templates(target: Path) -> tuple[list[Path], list[Path]]:
    """Copy missing templates and return (created, preserved) destination paths."""
    target.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    preserved: list[Path] = []
    for name in TEMPLATE_NAMES:
        source = TEMPLATE_DIR / name
        destination = target / name
        if destination.exists():
            preserved.append(destination)
            continue
        shutil.copy2(source, destination)
        created.append(destination)
    return created, preserved


def run(command: list[str], cwd: Path) -> None:
    """Run one visible dependency setup command."""
    print(f"+ {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    """Install missing editor templates and optionally development dependencies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=ROOT / ".vscode")
    parser.add_argument(
        "--install-deps",
        action="store_true",
        help="also run uv sync --extra dev and npm ci for the terminal frontend",
    )
    args = parser.parse_args()
    created, preserved = copy_missing_templates(args.target.expanduser().resolve())
    for path in created:
        print(f"Created {path}")
    for path in preserved:
        print(f"Preserved existing {path}")
    if args.install_deps:
        run(["uv", "sync", "--extra", "dev"], ROOT)
        run(["npm", "ci"], ROOT / "frontend" / "terminal")
    print("VS Code setup complete; existing files were not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
