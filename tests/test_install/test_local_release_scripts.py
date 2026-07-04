"""Tests for non-overwriting VS Code setup and versioned local source releases."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
common = importlib.import_module("local_release_common")
builder = importlib.import_module("build_local_release")
installer = importlib.import_module("install_local_release")
vscode_setup = importlib.import_module("setup_vscode")


def create_fake_release(root: Path, release_id: str) -> None:
    """Create the command layout required by activation without installing packages."""
    venv = root / "releases" / release_id / "venv"
    for name in common.LAUNCHER_NAMES:
        command = common.venv_command(venv, name)
        command.parent.mkdir(parents=True, exist_ok=True)
        command.write_text("placeholder", encoding="utf-8")


def test_vscode_setup_copies_missing_files_and_preserves_existing(tmp_path: Path) -> None:
    target = tmp_path / ".vscode"
    target.mkdir()
    settings = target / "settings.json"
    settings.write_text('{"personal": true}\n', encoding="utf-8")

    created, preserved = vscode_setup.copy_missing_templates(target)

    assert settings in preserved
    assert settings.read_text(encoding="utf-8") == '{"personal": true}\n'
    assert {path.name for path in created} == {"launch.json", "tasks.json", "extensions.json"}
    for path in created:
        assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)


def test_builder_reads_python_310_compatible_static_project_metadata() -> None:
    name, version = builder.project_metadata()
    assert name == "openharness-ai"
    assert version and version[0].isdigit()


def test_manifest_wheel_checksum_is_enforced(tmp_path: Path) -> None:
    wheel = tmp_path / "openharness.whl"
    wheel.write_bytes(b"expected bytes")
    manifest = tmp_path / common.MANIFEST_NAME
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project": "openharness-ai",
                "release_id": "test-release",
                "artifacts": [
                    {
                        "filename": wheel.name,
                        "kind": "wheel",
                        "sha256": common.sha256_file(wheel),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    _, resolved, digest = installer.wheel_from_manifest(manifest)
    assert resolved == wheel
    assert digest == common.sha256_file(wheel)

    wheel.write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="checksum mismatch"):
        installer.wheel_from_manifest(manifest)


def test_manifest_rejects_wheel_path_traversal(tmp_path: Path) -> None:
    manifest = tmp_path / common.MANIFEST_NAME
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project": "openharness-ai",
                "release_id": "test-release",
                "artifacts": [
                    {"filename": "../outside.whl", "kind": "wheel", "sha256": "irrelevant"}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="local .whl basename"):
        installer.wheel_from_manifest(manifest)


def test_activation_and_rollback_only_change_dedicated_launchers(tmp_path: Path) -> None:
    root = tmp_path / "source-releases"
    create_fake_release(root, "one")
    create_fake_release(root, "two")
    state = common.empty_state()
    state["releases"] = {"one": {}, "two": {}}

    common.activate_release(root, state, "one", record=True)
    state = common.load_state(root)
    common.activate_release(root, state, "two", record=True)
    installer.rollback(root)

    state = common.load_state(root)
    assert state["active"] == "one"
    for name in common.LAUNCHER_NAMES:
        launcher = common.launcher_path(root / "bin", name)
        assert common.is_managed_launcher(launcher, root)
        if common.os.name != "nt":
            assert launcher.resolve() == common.venv_command(
                root / "releases" / "one" / "venv", name
            )


def test_activation_refuses_non_managed_launcher(tmp_path: Path) -> None:
    root = tmp_path / "source-releases"
    create_fake_release(root, "one")
    state = common.empty_state()
    state["releases"] = {"one": {}}
    collision = common.launcher_path(root / "bin", "oh")
    collision.parent.mkdir(parents=True)
    collision.write_text("user-owned", encoding="utf-8")

    with pytest.raises(FileExistsError, match="non-managed launcher"):
        common.activate_release(root, state, "one", record=True)

    assert collision.read_text(encoding="utf-8") == "user-owned"


def test_activation_rejects_unsafe_release_id(tmp_path: Path) -> None:
    state = common.empty_state()
    state["releases"] = {"../escape": {}}
    with pytest.raises(ValueError, match="Unsafe local release ID"):
        common.activate_release(tmp_path, state, "../escape", record=True)


def test_shell_path_command_does_not_edit_profiles(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin with spaces"
    assert common.shell_path_command(bin_dir, "posix") == f"export PATH='{bin_dir}':\"$PATH\""
    assert str(bin_dir) in common.shell_path_command(bin_dir, "powershell")
