"""File-backed session memory for compact continuity.

Integration: This module participates in runtime support services such as compaction, sessions,
cron, extraction, and autodream.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve persistence schemas, task/time bounds, compaction continuity,
cancellation, atomic writes, and best-effort failure boundaries.
"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path

from openharness.config.paths import get_data_dir
from openharness.engine.messages import ConversationMessage, ToolResultBlock
from openharness.services.token_estimation import estimate_tokens
from openharness.utils.fs import atomic_write_text

MAX_SESSION_MEMORY_CHARS = 12_000
MAX_RECENT_LINES = 80


def get_session_memory_dir(cwd: str | Path) -> Path:
    """Return the project session-memory directory.

    Integration: Called by ``get_session_memory_path`` and collaborates with ``resolve``,
    ``path.mkdir``, ``hexdigest``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """

    root = Path(cwd).resolve()
    digest = sha1(str(root).encode("utf-8")).hexdigest()[:12]
    path = get_data_dir() / "session-memory" / f"{root.name}-{digest}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_session_memory_path(cwd: str | Path, session_id: str | None = None) -> Path:
    """Return the markdown session-memory path.

    Integration: Called by ``_handle_memory_session_command``,
    ``prepare_session_memory_metadata`` and collaborates with ``join``,
    ``get_session_memory_dir``, ``ch.isalnum``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    safe_session = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (session_id or "default"))
    return get_session_memory_dir(cwd) / f"{safe_session or 'default'}.md"


def prepare_session_memory_metadata(
    cwd: str | Path,
    tool_metadata: dict[str, object],
    *,
    session_id: str | None = None,
) -> Path:
    """Ensure metadata points compaction to the session-memory file.

    Integration: Called by ``QueryEngine._prepare_session_memory``,
    ``update_session_memory_file`` and collaborates with ``get_session_memory_path``,
    ``tool_metadata.get``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    sid = session_id or str(tool_metadata.get("session_id") or "default")
    path = get_session_memory_path(cwd, sid)
    tool_metadata["session_memory_path"] = str(path)
    return path


def get_session_memory_content(path: str | Path | None) -> str:
    """Read session memory content if available.

    Integration: Called by ``_handle_memory_session_command``,
    ``_build_file_session_memory_message`` and collaborates with ``expanduser``,
    ``candidate.exists``, ``candidate.read_text``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    exception and fallback behavior expected by callers.
    """

    if not path:
        return ""
    candidate = Path(path).expanduser()
    if not candidate.exists():
        return ""
    try:
        return candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def update_session_memory_file(
    cwd: str | Path,
    messages: list[ConversationMessage],
    *,
    tool_metadata: dict[str, object] | None = None,
    session_id: str | None = None,
) -> Path:
    """Update the deterministic session-memory checkpoint.

    Integration: Called by ``_handle_memory_session_command``,
    ``QueryEngine._update_session_memory`` and collaborates with
    ``prepare_session_memory_metadata``, ``build_session_memory_document``,
    ``atomic_write_text``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    path = prepare_session_memory_metadata(cwd, tool_metadata or {}, session_id=session_id)
    body = build_session_memory_document(messages, tool_metadata=tool_metadata)
    atomic_write_text(path, body)
    return path


def build_session_memory_document(
    messages: list[ConversationMessage],
    *,
    tool_metadata: dict[str, object] | None = None,
) -> str:
    """Build a compact markdown checkpoint for the current session.

    Integration: Called by ``update_session_memory_file`` and collaborates with
    ``lines.extend``, ``tool_metadata.get``, ``strip``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    state = tool_metadata.get("task_focus_state") if isinstance(tool_metadata, dict) else None
    goal = ""
    next_step = ""
    verified: list[str] = []
    artifacts: list[str] = []
    if isinstance(state, dict):
        goal = str(state.get("goal") or "").strip()
        next_step = str(state.get("next_step") or "").strip()
        verified = [str(item).strip() for item in state.get("verified_state", []) if str(item).strip()]
        artifacts = [str(item).strip() for item in state.get("active_artifacts", []) if str(item).strip()]

    lines = ["# Session Memory", ""]
    lines.extend(["## Current State", goal or "(no current goal recorded)", ""])
    if next_step:
        lines.extend(["## Next Step", next_step, ""])
    if verified:
        lines.extend(["## Verified Work", *[f"- {item}" for item in verified[-10:]], ""])
    if artifacts:
        lines.extend(["## Active Artifacts", *[f"- {item}" for item in artifacts[-10:]], ""])
    lines.extend(["## Recent Conversation", *_recent_message_lines(messages), ""])
    text = "\n".join(lines).strip() + "\n"
    if len(text) > MAX_SESSION_MEMORY_CHARS:
        text = text[:MAX_SESSION_MEMORY_CHARS].rsplit("\n", 1)[0]
        text += "\n\n> Session memory was truncated to stay within budget.\n"
    return text


def session_memory_to_compact_text(content: str) -> str:
    """Prepare persisted session memory for insertion across compact boundaries.

    Integration: Called by ``_build_file_session_memory_message`` and collaborates with
    ``content.strip``, ``estimate_tokens``, ``rsplit``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    stripped = content.strip()
    if not stripped:
        return ""
    if estimate_tokens(stripped) > 4_000:
        stripped = stripped[:MAX_SESSION_MEMORY_CHARS].rsplit("\n", 1)[0]
    return "Session memory checkpoint from earlier in this conversation:\n" + stripped


def _recent_message_lines(messages: list[ConversationMessage]) -> list[str]:
    """Derive recent message lines from the current inputs and subsystem state.

    Integration: Called by ``build_session_memory_document`` and collaborates with
    ``_summarize_message``, ``lines.append``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    lines: list[str] = []
    for message in messages[-MAX_RECENT_LINES:]:
        line = _summarize_message(message)
        if line:
            lines.append(f"- {line}")
    return lines or ["- (no recent messages)"]


def _summarize_message(message: ConversationMessage) -> str:
    """Summarize message for the enclosing subsystem.

    Integration: Used as an internal helper or callback at this module boundary and collaborates
    with ``any``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    text = " ".join(message.text.split())
    if text:
        return f"{message.role}: {text[:220]}"
    if message.tool_uses:
        return f"{message.role}: tool calls -> {', '.join(block.name for block in message.tool_uses[:6])}"
    if any(isinstance(block, ToolResultBlock) for block in message.content):
        return f"{message.role}: tool results returned"
    return f"{message.role}: [non-text content]"
