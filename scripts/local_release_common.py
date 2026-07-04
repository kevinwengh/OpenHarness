"""Shared, dependency-free helpers for source-built local OpenHarness releases."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


MANIFEST_NAME = "openharness-local-release.json"
STATE_SCHEMA_VERSION = 1
LAUNCHER_NAMES = ("oh", "openh", "openharness", "ohmo")
WINDOWS_LAUNCHER_MARKER = "REM Managed by OpenHarness local release installer"
SAFE_RELEASE_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


def validate_release_id(release_id: str) -> str:
    """Reject release identifiers that could escape or ambiguously name their directory."""
    if (
        not release_id
        or not release_id[0].isalnum()
        or any(character not in SAFE_RELEASE_ID_CHARS for character in release_id)
    ):
        raise ValueError(f"Unsafe local release ID: {release_id!r}")
    return release_id


def default_install_root() -> Path:
    """Return a platform-appropriate root that is separate from app configuration."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "OpenHarness" / "source-releases"
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "openharness" / "source-releases"


def venv_python(venv: Path) -> Path:
    """Return the Python executable for a virtual environment."""
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_command(venv: Path, name: str) -> Path:
    """Return one installed console command in a virtual environment."""
    if os.name == "nt":
        return venv / "Scripts" / f"{name}.exe"
    return venv / "bin" / name


def launcher_path(bin_dir: Path, name: str) -> Path:
    """Return the managed launcher path exposed to PATH."""
    return bin_dir / (f"{name}.cmd" if os.name == "nt" else name)


def sha256_file(path: Path) -> str:
    """Hash a file without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object and reject non-object top-level values."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """Atomically replace a JSON file in its existing filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def empty_state() -> dict[str, Any]:
    """Return a fresh installer state document."""
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "active": None,
        "history": [],
        "releases": {},
    }


def load_state(root: Path) -> dict[str, Any]:
    """Load and minimally validate installer-owned state."""
    path = root / "state.json"
    if not path.exists():
        return empty_state()
    state = read_json(path)
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported local release state schema in {path}")
    if not isinstance(state.get("history"), list) or not isinstance(state.get("releases"), dict):
        raise ValueError(f"Invalid local release state in {path}")
    return state


def is_managed_launcher(path: Path, root: Path) -> bool:
    """Return whether a launcher belongs to this install root."""
    if not path.exists() and not path.is_symlink():
        return True
    if os.name == "nt":
        try:
            return path.read_text(encoding="utf-8").startswith(WINDOWS_LAUNCHER_MARKER)
        except (OSError, UnicodeDecodeError):
            return False
    if not path.is_symlink():
        return False
    try:
        path.resolve(strict=False).relative_to((root / "releases").resolve())
    except ValueError:
        return False
    return True


def replace_launcher(path: Path, target: Path, root: Path) -> None:
    """Atomically create a managed launcher without replacing an unrelated file."""
    if not is_managed_launcher(path, root):
        raise FileExistsError(f"Refusing to replace non-managed launcher: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    if os.name == "nt":
        temporary.write_text(
            f'{WINDOWS_LAUNCHER_MARKER}\r\n@"{target}" %*\r\n', encoding="utf-8"
        )
    else:
        temporary.symlink_to(target)
    os.replace(temporary, path)


def activate_release(root: Path, state: dict[str, Any], release_id: str, *, record: bool) -> None:
    """Point all dedicated launchers at an installed release and persist state."""
    validate_release_id(release_id)
    releases = state["releases"]
    if release_id not in releases:
        raise ValueError(f"Unknown local release: {release_id}")
    release_dir = root / "releases" / release_id
    venv = release_dir / "venv"
    missing = [name for name in LAUNCHER_NAMES if not venv_command(venv, name).exists()]
    if missing:
        raise FileNotFoundError(f"Release {release_id} is missing commands: {', '.join(missing)}")

    bin_dir = root / "bin"
    for name in LAUNCHER_NAMES:
        path = launcher_path(bin_dir, name)
        if not is_managed_launcher(path, root):
            raise FileExistsError(f"Refusing to replace non-managed launcher: {path}")

    previous = state.get("active")
    for name in LAUNCHER_NAMES:
        replace_launcher(launcher_path(bin_dir, name), venv_command(venv, name), root)

    if record and previous and previous != release_id:
        history = [item for item in state["history"] if item != previous]
        state["history"] = (history + [previous])[-20:]
    state["active"] = release_id
    atomic_write_json(root / "state.json", state)


def shell_path_command(bin_dir: Path, shell: str) -> str:
    """Return a current-shell-only PATH command without editing a profile."""
    if shell == "powershell":
        escaped = str(bin_dir).replace("'", "''")
        return f"$env:Path = '{escaped};' + $env:Path"
    if shell == "cmd":
        return f'set "PATH={bin_dir};%PATH%"'
    escaped = str(bin_dir).replace("'", "'\"'\"'")
    return f"export PATH='{escaped}':\"$PATH\""


def isolated_runtime_env(state_root: Path) -> dict[str, str]:
    """Return an environment that cannot consume normal OpenHarness/ohmo state."""
    env = os.environ.copy()
    env["OPENHARNESS_CONFIG_DIR"] = str(state_root / "openharness")
    env["OHMO_WORKSPACE"] = str(state_root / "ohmo")
    env.setdefault("PYTHONUTF8", "1")
    return env


def platform_description() -> str:
    """Return a compact interpreter/platform label for a build manifest."""
    return f"{sys.platform}; Python {sys.version.split()[0]}"
