"""Lightweight code intelligence tool for Python workspaces.

Integration: This module participates in model-callable tools registered with the shared engine
governance path.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve Pydantic schemas, async ToolResult behavior, read-only policy,
context.cwd, hooks, sandboxing, output bounds, and registration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from openharness.services.lsp import (
    find_references,
    go_to_definition,
    hover,
    list_document_symbols,
    workspace_symbol_search,
)
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class LspToolInput(BaseModel):
    """Arguments for code intelligence queries.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    operation: Literal[
        "document_symbol",
        "workspace_symbol",
        "go_to_definition",
        "find_references",
        "hover",
    ] = Field(description="The code intelligence operation to perform")
    file_path: str | None = Field(default=None, description="Path to the source file for file-based operations")
    symbol: str | None = Field(default=None, description="Explicit symbol name to look up")
    line: int | None = Field(default=None, ge=1, description="1-based line number for position-based lookups")
    character: int | None = Field(default=None, ge=1, description="1-based character offset for position-based lookups")
    query: str | None = Field(default=None, description="Substring query for workspace_symbol")

    @model_validator(mode="after")
    def validate_arguments(self) -> "LspToolInput":
        """Validate arguments for the enclosing subsystem.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``model_validator``, ``ValueError``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        if self.operation == "workspace_symbol":
            if not self.query:
                raise ValueError("workspace_symbol requires query")
            return self
        if not self.file_path:
            raise ValueError(f"{self.operation} requires file_path")
        if self.operation == "document_symbol":
            return self
        if not self.symbol and self.line is None:
            raise ValueError(f"{self.operation} requires symbol or line")
        return self


class LspTool(BaseTool):
    """Read-only code intelligence for Python source files.

    Integration: Constructed or referenced by ``create_default_tool_registry``.

    Event loop: Async methods ``execute`` run on their caller's loop; instances must retain
    clear task, cancellation, and cleanup ownership.

    Change safety: Keep the input schema, read-only classification, async ``ToolResult``
    contract, permission metadata, hooks, sandbox behavior, and registration synchronized.
    """

    name = "lsp"
    description = (
        "Inspect Python code symbols, definitions, references, and hover information "
        "across the current workspace."
    )
    input_model = LspToolInput

    def is_read_only(self, arguments: LspToolInput) -> bool:
        """Classify whether this ``LspTool`` invocation can mutate state.

        Integration: Exposed through ``LspTool``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve conservative argument-aware classification used by permission
        policy expected by callers.

        Tool contract: Permission policy trusts this argument-aware classification before
        execution. Return ``True`` only when the invocation cannot mutate local files,
        processes, remote services, configuration, or shared runtime state; prefer a
        conservative ``False`` when uncertain.
        """
        del arguments
        return True

    async def execute(self, arguments: LspToolInput, context: ToolExecutionContext) -> ToolResult:
        """Execute one model-requested ``LspTool`` invocation.

        Integration: Exposed through ``LspTool`` and collaborates with ``context.cwd.resolve``,
        ``_resolve_path``, ``hover``.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block.

        Change safety: Preserve the asynchronous ``ToolResult`` contract, ``context.cwd``, and
        normalized operational failures; preserve permission, hook, sandbox, metadata, and
        output-size assumptions expected by callers.

        Tool contract: The engine validates the Pydantic input and applies hooks and permission
        policy before awaiting this method. Return ``ToolResult`` for expected operational
        failures, resolve paths from ``context.cwd``, keep output and metadata serializable and
        bounded, and do not block the event loop. Revisit sandbox routing, secret redaction,
        tool-result replay, and registration whenever execution behavior changes.
        """
        root = context.cwd.resolve()
        if arguments.operation == "workspace_symbol":
            results = workspace_symbol_search(root, arguments.query or "")
            return ToolResult(output=_format_symbol_locations(results, root))

        assert arguments.file_path is not None  # validated above
        file_path = _resolve_path(root, arguments.file_path)
        if not file_path.exists():
            return ToolResult(output=f"File not found: {file_path}", is_error=True)
        if file_path.suffix != ".py":
            return ToolResult(output="The lsp tool currently supports Python files only.", is_error=True)

        if arguments.operation == "document_symbol":
            return ToolResult(output=_format_symbol_locations(list_document_symbols(file_path), root))

        if arguments.operation == "go_to_definition":
            results = go_to_definition(
                root=root,
                file_path=file_path,
                symbol=arguments.symbol,
                line=arguments.line,
                character=arguments.character,
            )
            return ToolResult(output=_format_symbol_locations(results, root))

        if arguments.operation == "find_references":
            results = find_references(
                root=root,
                file_path=file_path,
                symbol=arguments.symbol,
                line=arguments.line,
                character=arguments.character,
            )
            return ToolResult(output=_format_references(results, root))

        result = hover(
            root=root,
            file_path=file_path,
            symbol=arguments.symbol,
            line=arguments.line,
            character=arguments.character,
        )
        if result is None:
            return ToolResult(output="(no hover result)")
        parts = [
            f"{result.kind} {result.name}",
            f"path: {_display_path(result.path, root)}:{result.line}:{result.character}",
        ]
        if result.signature:
            parts.append(f"signature: {result.signature}")
        if result.docstring:
            parts.append(f"docstring: {result.docstring.strip()}")
        return ToolResult(output="\n".join(parts))


def _resolve_path(base: Path, candidate: str) -> Path:
    """Resolve path for the enclosing subsystem.

    Integration: Used as an internal helper or callback at this module boundary and collaborates
    with ``expanduser``, ``path.resolve``, ``path.is_absolute``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _display_path(path: Path, root: Path) -> str:
    """Return the filesystem path for display.

    Integration: Called by ``LspTool.execute``, ``_format_symbol_locations`` and collaborates
    with ``path.relative_to``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _format_symbol_locations(results, root: Path) -> str:
    """Format symbol locations for the enclosing subsystem.

    Integration: Called by ``LspTool.execute`` and collaborates with ``join``, ``lines.append``,
    ``_display_path``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if not results:
        return "(no results)"
    lines = []
    for item in results:
        lines.append(
            f"{item.kind} {item.name} - {_display_path(item.path, root)}:{item.line}:{item.character}"
        )
        if item.signature:
            lines.append(f"  signature: {item.signature}")
        if item.docstring:
            lines.append(f"  docstring: {item.docstring.strip()}")
    return "\n".join(lines)


def _format_references(results: list[tuple[Path, int, str]], root: Path) -> str:
    """Format references for the enclosing subsystem.

    Integration: Called by ``LspTool.execute`` and collaborates with ``join``,
    ``_display_path``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if not results:
        return "(no results)"
    return "\n".join(f"{_display_path(path, root)}:{line}:{text}" for path, line, text in results)
