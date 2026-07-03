"""Content search tool with a pure-Python fallback.

Integration: This module participates in model-callable tools registered with the shared engine
governance path.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve Pydantic schemas, async ToolResult behavior, read-only policy,
context.cwd, hooks, sandboxing, output bounds, and registration.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class GrepToolInput(BaseModel):
    """Arguments for the grep tool.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    pattern: str = Field(description="Regular expression to search for")
    root: str | None = Field(
        default=None,
        description="Search root directory or file. For multiple roots, call grep separately per root.",
    )
    file_glob: str = Field(default="**/*")
    case_sensitive: bool = Field(default=True)
    limit: int = Field(default=200, ge=1, le=2000)
    timeout_seconds: int = Field(default=20, ge=1, le=120)


class GrepTool(BaseTool):
    """Search text files for a regex pattern.

    Integration: Constructed or referenced by ``create_default_tool_registry``.

    Event loop: Async methods ``execute`` run on their caller's loop; instances must retain
    clear task, cancellation, and cleanup ownership.

    Change safety: Keep the input schema, read-only classification, async ``ToolResult``
    contract, permission metadata, hooks, sandbox behavior, and registration synchronized.
    """

    name = "grep"
    description = "Search file contents with a regular expression."
    input_model = GrepToolInput

    def is_read_only(self, arguments: GrepToolInput) -> bool:
        """Classify whether this ``GrepTool`` invocation can mutate state.

        Integration: Exposed through ``GrepTool``.

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

    async def execute(self, arguments: GrepToolInput, context: ToolExecutionContext) -> ToolResult:
        """Execute one model-requested ``GrepTool`` invocation.

        Integration: Exposed through ``GrepTool`` and collaborates with ``root.is_file``,
        ``ToolResult``, ``_resolve_path``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the asynchronous ``ToolResult`` contract, ``context.cwd``, and
        normalized operational failures; preserve permission, hook, sandbox, metadata, and
        output-size assumptions expected by callers.

        Tool contract: The engine validates the Pydantic input and applies hooks and permission
        policy before awaiting this method. Return ``ToolResult`` for expected operational
        failures, resolve paths from ``context.cwd``, keep output and metadata serializable and
        bounded, and do not block the event loop. Revisit sandbox routing, secret redaction,
        tool-result replay, and registration whenever execution behavior changes.
        """
        root = _resolve_path(context.cwd, arguments.root) if arguments.root else context.cwd
        if not root.exists():
            return ToolResult(
                output=(
                    f"Search root does not exist: {root}\n"
                    "If you intended multiple roots, call grep separately for each root."
                ),
                is_error=True,
            )
        if root.is_file():
            display_base = _display_base(root, context.cwd)
            matches = await _rg_grep_file(
                path=root,
                pattern=arguments.pattern,
                case_sensitive=arguments.case_sensitive,
                limit=arguments.limit,
                display_base=display_base,
                timeout_seconds=arguments.timeout_seconds,
            )
            if matches is not None:
                return _format_rg_result(matches, arguments.timeout_seconds)

            return ToolResult(
                output=_python_grep_files(
                    paths=[root],
                    pattern=arguments.pattern,
                    case_sensitive=arguments.case_sensitive,
                    limit=arguments.limit,
                    display_base=display_base,
                )
            )

        # Prefer ripgrep for performance; fallback to Python when unavailable.
        matches = await _rg_grep(
            root=root,
            pattern=arguments.pattern,
            file_glob=arguments.file_glob,
            case_sensitive=arguments.case_sensitive,
            limit=arguments.limit,
            timeout_seconds=arguments.timeout_seconds,
        )
        if matches is not None:
            return _format_rg_result(matches, arguments.timeout_seconds)

        # Python fallback (kept for portability).
        return ToolResult(
            output=_python_grep_files(
                paths=root.glob(arguments.file_glob),
                pattern=arguments.pattern,
                case_sensitive=arguments.case_sensitive,
                limit=arguments.limit,
                display_base=root,
            )
        )


def _display_base(path: Path, cwd: Path) -> Path:
    """Derive display base from the current inputs and subsystem state.

    Integration: Called by ``GrepTool.execute`` and collaborates with ``path.relative_to``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    try:
        path.relative_to(cwd)
    except ValueError:
        return path.parent
    return cwd


def _python_grep_files(
    *,
    paths,
    pattern: str,
    case_sensitive: bool,
    limit: int,
    display_base: Path,
) -> str:
    # Python fallback (kept for portability).
    """Derive python grep files from the current inputs and subsystem state.

    Integration: Called by ``GrepTool.execute`` and collaborates with ``join``, ``re.compile``,
    ``raw.decode``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        return f"(invalid regex pattern '{pattern}': {exc})"
    collected: list[str] = []

    for path in paths:
        if len(collected) >= limit:
            break
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line):
                collected.append(f"{_format_path(path, display_base)}:{line_no}:{line}")
                if len(collected) >= limit:
                    break

    if not collected:
        return "(no matches)"
    return "\n".join(collected)


def _resolve_path(base: Path, candidate: str | None) -> Path:
    """Resolve path for the enclosing subsystem.

    Integration: Used as an internal helper or callback at this module boundary and collaborates
    with ``expanduser``, ``path.resolve``, ``path.is_absolute``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    path = Path(candidate or ".").expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _format_rg_result(matches: list[str], timeout_seconds: int) -> ToolResult:
    """Format rg result for the enclosing subsystem.

    Integration: Called by ``GrepTool.execute`` and collaborates with ``ToolResult``, ``join``,
    ``_timeout_marker``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    timed_out = bool(matches and matches[-1] == _timeout_marker(timeout_seconds))
    rendered = matches[:-1] if timed_out else matches
    output = "\n".join(rendered) if rendered else "(no matches)"
    if timed_out:
        output = (
            f"{output}\n\n[grep timed out after {timeout_seconds} seconds]"
            if output != "(no matches)"
            else f"[grep timed out after {timeout_seconds} seconds]"
        )
    return ToolResult(output=output, is_error=timed_out)


async def _rg_grep(
    *,
    root: Path,
    pattern: str,
    file_glob: str,
    case_sensitive: bool,
    limit: int,
    timeout_seconds: int,
) -> list[str] | None:
    """Return matches using ripgrep, or None if ripgrep is unavailable.

    Integration: Called by ``GrepTool.execute`` and collaborates with ``shutil.which``,
    ``cmd.extend``, ``get_docker_sandbox``.

    Event loop: This coroutine coordinates child tasks; preserve cancellation, completion, and
    exception ownership.

    Change safety: Preserve argv boundaries, timeouts, and child cleanup; preserve exception and
    fallback behavior expected by callers.
    """
    rg = shutil.which("rg")
    if not rg:
        return None

    include_hidden = (root / ".git").exists() or (root / ".gitignore").exists()
    cmd: list[str] = [
        rg,
        "--no-heading",
        "--line-number",
        "--color",
        "never",
    ]
    if include_hidden:
        cmd.append("--hidden")
    if not case_sensitive:
        cmd.append("-i")
    if file_glob:
        cmd.extend(["--glob", file_glob])
    # `--` ensures patterns like `-foo` aren't parsed as flags.
    cmd.extend(["--", pattern, "."])

    from openharness.sandbox.session import get_docker_sandbox

    session = get_docker_sandbox()
    if session is not None and session.is_running:
        process = await session.exec_command(
            cmd,
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    else:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=8 * 1024 * 1024,  # 8 MB per line — avoids LimitOverrunError on long lines
        )

    matches: list[str] = []
    try:
        await asyncio.wait_for(
            _collect_rg_matches(process, matches, limit=limit),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        matches.append(_timeout_marker(timeout_seconds))
        await _terminate_process(process)
    except asyncio.CancelledError:
        await _terminate_process(process)
        raise
    finally:
        if len(matches) >= limit and process.returncode is None:
            await _terminate_process(process)
        elif process.returncode is None:
            await process.wait()

    # rg exits 0 when matches are found, 1 when none are found.
    # Any other return code indicates an error; fall back to Python.
    if process.returncode in {0, 1, -15, -9}:
        return matches
    return None


async def _rg_grep_file(
    *,
    path: Path,
    pattern: str,
    case_sensitive: bool,
    limit: int,
    display_base: Path,
    timeout_seconds: int,
) -> list[str] | None:
    """Run the rg grep file workflow through its asynchronous collaborators.

    Integration: Called by ``GrepTool.execute`` and collaborates with ``shutil.which``,
    ``cmd.extend``, ``get_docker_sandbox``.

    Event loop: This coroutine coordinates child tasks; preserve cancellation, completion, and
    exception ownership.

    Change safety: Preserve argv boundaries, timeouts, and child cleanup; preserve exception and
    fallback behavior expected by callers.
    """
    rg = shutil.which("rg")
    if not rg:
        return None

    cmd: list[str] = [
        rg,
        "--no-heading",
        "--line-number",
        "--color",
        "never",
    ]
    if not case_sensitive:
        cmd.append("-i")
    cmd.extend(["--", pattern, path.name])

    from openharness.sandbox.session import get_docker_sandbox

    session = get_docker_sandbox()
    if session is not None and session.is_running:
        process = await session.exec_command(
            cmd,
            cwd=path.parent,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    else:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(path.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=8 * 1024 * 1024,  # 8 MB per line — avoids LimitOverrunError on long lines
        )

    matches: list[str] = []
    try:
        await asyncio.wait_for(
            _collect_rg_file_matches(
                process,
                matches,
                limit=limit,
                path=path,
                display_base=display_base,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        matches.append(_timeout_marker(timeout_seconds))
        await _terminate_process(process)
    except asyncio.CancelledError:
        await _terminate_process(process)
        raise
    finally:
        if len(matches) >= limit and process.returncode is None:
            await _terminate_process(process)
        elif process.returncode is None:
            await process.wait()

    if process.returncode in {0, 1, -15, -9}:
        return matches
    return None


def _timeout_marker(timeout_seconds: int) -> str:
    """Derive timeout marker from the current inputs and subsystem state.

    Integration: Called by ``_format_rg_result``, ``_rg_grep``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return f"__OPENHARNESS_GREP_TIMEOUT__:{timeout_seconds}"


async def _collect_rg_matches(
    process: asyncio.subprocess.Process,
    matches: list[str],
    *,
    limit: int,
) -> None:
    """Run the collect rg matches workflow through its asynchronous collaborators.

    Integration: Called by ``_rg_grep`` and collaborates with ``rstrip``, ``matches.append``,
    ``process.stdout.readline``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    assert process.stdout is not None
    while len(matches) < limit:
        try:
            raw = await process.stdout.readline()
        except ValueError:
            # Line exceeded the stream buffer limit; skip it and continue.
            continue
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        if line:
            matches.append(line)


async def _collect_rg_file_matches(
    process: asyncio.subprocess.Process,
    matches: list[str],
    *,
    limit: int,
    path: Path,
    display_base: Path,
) -> None:
    """Run the collect rg file matches workflow through its asynchronous collaborators.

    Integration: Called by ``_rg_grep_file`` and collaborates with ``rstrip``,
    ``matches.append``, ``process.stdout.readline``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    assert process.stdout is not None
    while len(matches) < limit:
        try:
            raw = await process.stdout.readline()
        except ValueError:
            # Line exceeded the stream buffer limit; skip it and continue.
            continue
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        if not line:
            continue
        matches.append(f"{_format_path(path, display_base)}:{line}")


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    """Run the terminate process workflow through its asynchronous collaborators.

    Integration: Used as an internal helper or callback at this module boundary and collaborates
    with ``process.terminate``, ``asyncio.wait_for``, ``process.kill``.

    Event loop: This coroutine coordinates child tasks; preserve cancellation, completion, and
    exception ownership.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
    return None


def _format_path(path: Path, display_base: Path) -> str:
    """Format path for the enclosing subsystem.

    Integration: Called by ``_python_grep_files``, ``_collect_rg_file_matches`` and collaborates
    with ``path.relative_to``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    try:
        return str(path.relative_to(display_base))
    except ValueError:
        return str(path)
