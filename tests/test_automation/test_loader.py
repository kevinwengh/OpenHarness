from __future__ import annotations

import yaml

from openharness.automation.loader import load_workflow_definitions

from .conftest import workflow_payload


def _write(path, payload) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_loader_orders_definitions_and_reports_invalid_files(tmp_path) -> None:
    root = tmp_path / "automations"
    root.mkdir()
    low = workflow_payload(id="low", priority=1)
    high = workflow_payload(id="high", priority=20)
    _write(root / "low.yaml", low)
    _write(root / "high.yml", high)
    (root / "broken.yaml").write_text("steps: [", encoding="utf-8")
    (root / "ignored.txt").write_text("not yaml", encoding="utf-8")

    result = load_workflow_definitions(root)

    assert [definition.id for definition in result.definitions] == ["high", "low"]
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].path.name == "broken.yaml"
    assert "cannot parse YAML" in result.diagnostics[0].message


def test_loader_rejects_all_duplicate_ids(tmp_path) -> None:
    root = tmp_path / "automations"
    root.mkdir()
    _write(root / "one.yaml", workflow_payload(id="duplicate"))
    _write(root / "two.yaml", workflow_payload(id="duplicate", priority=99))

    result = load_workflow_definitions(root)

    assert result.definitions == ()
    assert len(result.diagnostics) == 2
    assert all("duplicate workflow ID" in item.message for item in result.diagnostics)


def test_loader_enforces_size_and_count_bounds(tmp_path) -> None:
    root = tmp_path / "automations"
    root.mkdir()
    _write(root / "first.yaml", workflow_payload(id="first"))
    _write(root / "second.yaml", workflow_payload(id="second"))

    result = load_workflow_definitions(root, max_definitions=1, max_definition_bytes=10)

    assert result.definitions == ()
    assert {item.path.name for item in result.diagnostics} == {"first.yaml", "second.yaml"}
    assert any("exceeds 10 bytes" in item.message for item in result.diagnostics)
    assert any("definition limit" in item.message for item in result.diagnostics)


def test_loader_returns_empty_result_for_missing_root(tmp_path) -> None:
    result = load_workflow_definitions(tmp_path / "missing")
    assert result.definitions == ()
    assert result.diagnostics == ()


def test_loader_rejects_duplicate_yaml_keys_and_aliases(tmp_path) -> None:
    root = tmp_path / "automations"
    root.mkdir()
    duplicate = yaml.safe_dump(workflow_payload(), sort_keys=False) + "priority: 99\n"
    (root / "duplicate-key.yaml").write_text(duplicate, encoding="utf-8")
    (root / "alias.yaml").write_text(
        "version: 1\nid: alias\nshared: &shared [one]\ncopy: *shared\n",
        encoding="utf-8",
    )

    result = load_workflow_definitions(root)

    assert result.definitions == ()
    assert len(result.diagnostics) == 2
    assert all("cannot parse YAML" in item.message for item in result.diagnostics)
    assert any("duplicate key" in item.message for item in result.diagnostics)
    assert any("aliases are not supported" in item.message for item in result.diagnostics)


def test_loader_rejects_plaintext_credentials_but_allows_aliases(tmp_path) -> None:
    root = tmp_path / "automations"
    root.mkdir()
    secret_key = workflow_payload(id="secret-key")
    secret_key["steps"][1]["with"]["api_key"] = "plaintext-value"
    token_value = workflow_payload(id="token-value")
    token_value["steps"][1]["with"]["content"] = "xoxb-1234567890-secret"
    alias = workflow_payload(id="alias")
    alias["steps"][1]["with"]["credential_alias"] = "slack-primary"
    _write(root / "secret-key.yaml", secret_key)
    _write(root / "token-value.yaml", token_value)
    _write(root / "alias.yaml", alias)

    result = load_workflow_definitions(root)

    assert [definition.id for definition in result.definitions] == ["alias"]
    assert len(result.diagnostics) == 2
    assert all(
        "plaintext credentials are not allowed" in item.message
        for item in result.diagnostics
    )
