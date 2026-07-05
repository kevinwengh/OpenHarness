#!/usr/bin/env python3
"""Validate and build a source checkout into a locally installable release."""

from __future__ import annotations

import argparse
import configparser
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from local_release_common import MANIFEST_NAME, isolated_runtime_env, platform_description, sha256_file


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    """Run one visible validation/build command and stop on failure."""
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def git_value(*args: str) -> str | None:
    """Return compact Git output when the checkout is a repository."""
    result = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def project_metadata() -> tuple[str, str]:
    """Read static project name/version fields without requiring Python 3.11 tomllib."""
    in_project = False
    values: dict[str, str] = {}
    for raw_line in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "[project]":
            in_project = True
            continue
        if in_project and line.startswith("["):
            break
        if in_project and "=" in line:
            key, value = (part.strip() for part in line.split("=", 1))
            if key in {"name", "version"} and value.startswith('"') and value.endswith('"'):
                values[key] = value[1:-1]
    if set(values) != {"name", "version"}:
        raise RuntimeError("Could not read project name and version from pyproject.toml")
    return values["name"], values["version"]


def inspect_wheel(path: Path) -> None:
    """Require the packages, entrypoints, and reproducible frontend inputs."""
    required_files = {
        "openharness/__init__.py",
        "ohmo/__init__.py",
        "openharness/_frontend/package.json",
        "openharness/_frontend/package-lock.json",
        "openharness/_frontend/src/index.tsx",
        "openharness/_web/index.html",
    }
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        missing = sorted(required_files - names)
        if missing:
            raise RuntimeError(f"Wheel is missing required files: {', '.join(missing)}")
        web_assets = {
            Path(name).suffix
            for name in names
            if name.startswith("openharness/_web/assets/")
        }
        if not {".css", ".js"}.issubset(web_assets):
            raise RuntimeError("Wheel must contain the built web UI CSS and JavaScript assets")
        entrypoint_names = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        if len(entrypoint_names) != 1:
            raise RuntimeError("Wheel must contain exactly one entry_points.txt")
        parser = configparser.ConfigParser()
        parser.read_string(archive.read(entrypoint_names[0]).decode("utf-8"))
        expected = {
            "oh": "openharness.cli:app",
            "openh": "openharness.cli:app",
            "openharness": "openharness.cli:app",
            "ohmo": "ohmo.cli:app",
        }
        actual = dict(parser.items("console_scripts")) if parser.has_section("console_scripts") else {}
        if any(actual.get(name) != target for name, target in expected.items()):
            raise RuntimeError(f"Unexpected console scripts in wheel: {actual}")


def artifact_record(path: Path, kind: str) -> dict[str, object]:
    """Describe one immutable build artifact."""
    return {
        "filename": path.name,
        "kind": kind,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def build_release(output_dir: Path, *, quick: bool) -> Path:
    """Run checks, build into a staging directory, inspect, and publish locally."""
    commit = git_value("rev-parse", "--short=12", "HEAD") or "no-git"
    dirty = bool(git_value("status", "--porcelain"))
    branch = git_value("branch", "--show-current")
    output_dir.mkdir(parents=True, exist_ok=True)
    if not quick:
        verification_root = output_dir.parent / "verify-state"
        env = isolated_runtime_env(verification_root)
        run(["uv", "run", "ruff", "check", "src", "tests", "scripts"])
        run(["uv", "run", "python", "scripts/check_docs.py"])
        run(["uv", "run", "pytest", "-q"], env=env)
        run(["npm", "ci"], cwd=ROOT / "frontend" / "terminal")
        run(["npx", "tsc", "--noEmit"], cwd=ROOT / "frontend" / "terminal")
        run(["npm", "ci"], cwd=ROOT / "frontend" / "web")
        run(["npm", "test"], cwd=ROOT / "frontend" / "web")
        run(["npm", "run", "build"], cwd=ROOT / "frontend" / "web")

    with tempfile.TemporaryDirectory(prefix="openharness-build-") as temporary:
        staging = Path(temporary)
        run(["uv", "build", "--out-dir", str(staging)])
        wheels = list(staging.glob("*.whl"))
        sdists = list(staging.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise RuntimeError("Expected exactly one wheel and one source distribution")
        inspect_wheel(wheels[0])
        copied_wheel = output_dir / wheels[0].name
        copied_sdist = output_dir / sdists[0].name
        shutil.copy2(wheels[0], copied_wheel)
        shutil.copy2(sdists[0], copied_sdist)

    project_name, project_version = project_metadata()
    release_id = f"{project_version}-{commit}"
    if dirty:
        release_id += f"-dirty-{time.strftime('%Y%m%d%H%M%S', time.gmtime())}"
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "project": project_name,
        "version": project_version,
        "source": {
            "commit": commit,
            "dirty": dirty,
            "branch": branch,
        },
        "built_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "builder": platform_description(),
        "artifacts": [
            artifact_record(copied_wheel, "wheel"),
            artifact_record(copied_sdist, "sdist"),
        ],
    }
    manifest_path = output_dir / MANIFEST_NAME
    temporary_manifest = manifest_path.with_suffix(".json.tmp")
    temporary_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest_path)
    print(f"Built local release {release_id}")
    print(f"Manifest: {manifest_path}")
    return manifest_path


def parse_args() -> argparse.Namespace:
    """Parse the intentionally small local-build interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / ".local-release" / "dist",
        help="artifact directory (default: .local-release/dist)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="build and inspect only; skip Ruff, docs, pytest, npm ci, and TypeScript checks",
    )
    return parser.parse_args()


def main() -> int:
    """Build a local release and return a conventional process status."""
    args = parse_args()
    build_release(args.output_dir.expanduser().resolve(), quick=args.quick)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
