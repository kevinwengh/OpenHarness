"""Bounded YAML discovery for trusted automation workflow definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken

from openharness.automation.models import WorkflowDefinition

MAX_DEFINITION_BYTES = 256 * 1024
MAX_DEFINITIONS = 100


class _WorkflowSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects ambiguous duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _WorkflowSafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict:
    loader.flatten_mapping(node)
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_WorkflowSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True)
class DefinitionDiagnostic:
    path: Path
    message: str
    workflow_id: str | None = None


@dataclass(frozen=True)
class DefinitionLoadResult:
    definitions: tuple[WorkflowDefinition, ...]
    diagnostics: tuple[DefinitionDiagnostic, ...]


def load_workflow_definitions(
    root: str | Path,
    *,
    max_definition_bytes: int = MAX_DEFINITION_BYTES,
    max_definitions: int = MAX_DEFINITIONS,
) -> DefinitionLoadResult:
    """Load valid direct-child YAML definitions without executing file content."""

    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        return DefinitionLoadResult(definitions=(), diagnostics=())
    if not root_path.is_dir():
        return DefinitionLoadResult(
            definitions=(),
            diagnostics=(DefinitionDiagnostic(root_path, "automation root is not a directory"),),
        )

    candidates = sorted(
        path for path in root_path.iterdir() if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}
    )
    diagnostics: list[DefinitionDiagnostic] = []
    if len(candidates) > max_definitions:
        for path in candidates[max_definitions:]:
            diagnostics.append(
                DefinitionDiagnostic(path, f"definition limit of {max_definitions} exceeded")
            )
        candidates = candidates[:max_definitions]

    loaded: list[tuple[Path, WorkflowDefinition]] = []
    for path in candidates:
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root_path)
        except (OSError, ValueError):
            diagnostics.append(DefinitionDiagnostic(path, "definition must stay within its root"))
            continue
        try:
            size = resolved.stat().st_size
        except OSError as exc:
            diagnostics.append(DefinitionDiagnostic(path, f"cannot stat definition: {exc}"))
            continue
        if size > max_definition_bytes:
            diagnostics.append(
                DefinitionDiagnostic(
                    path,
                    f"definition exceeds {max_definition_bytes} bytes",
                )
            )
            continue
        try:
            text = resolved.read_text(encoding="utf-8")
            if any(isinstance(token, AliasToken) for token in yaml.scan(text)):
                raise yaml.YAMLError("YAML aliases are not supported in workflow definitions")
            raw = yaml.load(text, Loader=_WorkflowSafeLoader)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            diagnostics.append(DefinitionDiagnostic(path, f"cannot parse YAML: {exc}"))
            continue
        if not isinstance(raw, dict):
            diagnostics.append(DefinitionDiagnostic(path, "definition must be a YAML object"))
            continue
        try:
            definition = WorkflowDefinition.model_validate(raw)
        except ValidationError as exc:
            diagnostics.append(DefinitionDiagnostic(path, _validation_message(exc), raw.get("id")))
            continue
        loaded.append((path, definition))

    paths_by_id: dict[str, list[Path]] = {}
    for path, definition in loaded:
        paths_by_id.setdefault(definition.id, []).append(path)
    duplicates = {workflow_id for workflow_id, paths in paths_by_id.items() if len(paths) > 1}
    for workflow_id in sorted(duplicates):
        for path in paths_by_id[workflow_id]:
            diagnostics.append(
                DefinitionDiagnostic(path, f"duplicate workflow ID {workflow_id!r}", workflow_id)
            )

    definitions = tuple(
        definition
        for _, definition in sorted(loaded, key=lambda item: (-item[1].priority, item[1].id))
        if definition.id not in duplicates
    )
    return DefinitionLoadResult(
        definitions=definitions,
        diagnostics=tuple(sorted(diagnostics, key=lambda item: (str(item.path), item.message))),
    )


def _validation_message(exc: ValidationError) -> str:
    errors = exc.errors(include_url=False)
    if not errors:
        return "definition validation failed"
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", ())) or "definition"
    message = str(first.get("msg") or "invalid value")
    remaining = len(errors) - 1
    suffix = f" (+{remaining} more errors)" if remaining else ""
    return f"validation failed at {location}: {message}{suffix}"
