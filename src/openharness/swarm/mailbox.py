"""File-based async message queue for leader-worker communication in OpenHarness swarms.

Each message is stored as an individual JSON file:
    ~/.openharness/teams/<team>/agents/<agent_id>/inbox/<timestamp>_<message_id>.json

Atomic writes use a .tmp file followed by os.rename to prevent partial reads.

Integration: This module participates in multi-agent team, mailbox, permission, subprocess, and
worktree coordination.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve identity and mailbox schemas, lock/atomicity, cancellation, permission
routing, Git isolation, and teardown.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from openharness.swarm.lockfile import exclusive_file_lock


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

MessageType = Literal[
    "user_message",
    "permission_request",
    "permission_response",
    "sandbox_permission_request",
    "sandbox_permission_response",
    "shutdown",
    "idle_notification",
]


@dataclass
class MailboxMessage:
    """A single message exchanged between swarm agents.

    Integration: Constructed or referenced by ``InProcessBackend.send_message``,
    ``_make_message``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    id: str
    type: MessageType
    sender: str
    recipient: str
    payload: dict[str, Any]
    timestamp: float
    read: bool = False

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize this record into its persisted dictionary shape.

        Integration: Exposed through ``MailboxMessage``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return {
            "id": self.id,
            "type": self.type,
            "sender": self.sender,
            "recipient": self.recipient,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "read": self.read,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MailboxMessage":
        """Reconstruct this record from its persisted dictionary shape.

        Integration: Exposed through ``MailboxMessage`` and collaborates with ``cls``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return cls(
            id=data["id"],
            type=data["type"],
            sender=data["sender"],
            recipient=data["recipient"],
            payload=data.get("payload", {}),
            timestamp=data["timestamp"],
            read=data.get("read", False),
        )


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------


def get_team_dir(team_name: str) -> Path:
    """Return ~/.openharness/teams/<team_name>/

    Integration: Called by ``get_agent_mailbox_dir``, ``get_permission_dir`` and collaborates
    with ``base.mkdir``, ``Path.home``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    base = Path.home() / ".openharness" / "teams" / team_name
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_agent_mailbox_dir(team_name: str, agent_id: str) -> Path:
    """Return ~/.openharness/teams/<team_name>/agents/<agent_id>/inbox/

    Integration: Called by ``TeammateMailbox.get_mailbox_dir`` and collaborates with
    ``inbox.mkdir``, ``get_team_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    inbox = get_team_dir(team_name) / "agents" / agent_id / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    return inbox


# ---------------------------------------------------------------------------
# TeammateMailbox
# ---------------------------------------------------------------------------


class TeammateMailbox:
    """File-based mailbox for a single agent within a swarm team.

    Each message lives in its own JSON file named ``<timestamp>_<id>.json``
    inside the agent's inbox directory.  Writes are atomic: the payload is
    first written to a ``.tmp`` file, then renamed into place so that readers
    never see a partial message.

    Integration: Constructed or referenced by ``start_in_process_teammate``,
    ``InProcessBackend.send_message``.

    Event loop: Async methods ``write``, ``read_all``, ``mark_read``, ``clear`` run on their
    caller's loop; instances must retain clear task, cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self, team_name: str, agent_id: str) -> None:
        """Initialize ``TeammateMailbox`` and bind its runtime dependencies.

        Integration: Exposed through ``TeammateMailbox``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.team_name = team_name
        self.agent_id = agent_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_mailbox_dir(self) -> Path:
        """Return the inbox directory path, creating it if necessary.

        Integration: Called by ``TeammateMailbox._lock_path``, ``TeammateMailbox.write`` and
        collaborates with ``get_agent_mailbox_dir``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return get_agent_mailbox_dir(self.team_name, self.agent_id)

    def _lock_path(self) -> Path:
        """Return the filesystem path for lock.

        Integration: Exposed through ``TeammateMailbox`` and collaborates with
        ``get_mailbox_dir``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self.get_mailbox_dir() / ".write_lock"

    async def write(self, msg: MailboxMessage) -> None:
        """Atomically write *msg* to the inbox as a JSON file.

        The file is first written to ``<name>.tmp`` then renamed into the
        inbox directory so that concurrent readers never observe a partial
        write.

        This method uses a thread pool for the blocking I/O operations and
        acquires an exclusive lock to prevent concurrent write conflicts.

        Integration: Called by ``run_ohmo_print_mode``, ``run_ohmo_print_mode._render_event``
        and collaborates with ``get_mailbox_dir``, ``json.dumps``, ``asyncio.get_event_loop``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O; retain lock scope and release behavior.

        Change safety: Preserve path isolation, encoding, and persistence side effects expected
        by callers.
        """
        inbox = self.get_mailbox_dir()
        filename = f"{msg.timestamp:.6f}_{msg.id}.json"
        final_path = inbox / filename
        tmp_path = inbox / f"{filename}.tmp"
        lock_path = inbox / ".write_lock"

        payload = json.dumps(msg.to_dict(), indent=2)

        def _write_atomic() -> None:
            """Write atomic for the enclosing subsystem.

            Integration: Used as an internal helper or callback at this module boundary and
            collaborates with ``exclusive_file_lock``, ``tmp_path.write_text``, ``os.replace``.

            Concurrency: This is synchronous; preserve deterministic behavior for its direct
            callers; retain lock scope and release behavior.

            Change safety: Preserve path isolation, encoding, and persistence side effects
            expected by callers.
            """
            with exclusive_file_lock(lock_path):
                tmp_path.write_text(payload, encoding="utf-8")
                os.replace(tmp_path, final_path)

        # Offload blocking I/O to thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_atomic)

    async def read_all(self, unread_only: bool = True) -> list[MailboxMessage]:
        """Return messages from the inbox, sorted by timestamp (oldest first).

        Args:
            unread_only: When *True* (default) only unread messages are
                returned.  Pass *False* to retrieve all messages including
                already-read ones.

        Integration: Called by ``_drain_mailbox``, ``poll_permission_response`` and collaborates
        with ``get_mailbox_dir``, ``asyncio.get_event_loop``, ``loop.run_in_executor``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
        exception and fallback behavior expected by callers.
        """
        inbox = self.get_mailbox_dir()

        def _read_all() -> list[MailboxMessage]:
            """Read all for the enclosing subsystem.

            Integration: Used as an internal helper or callback at this module boundary and
            collaborates with ``inbox.glob``, ``path.name.startswith``, ``path.name.endswith``.

            Concurrency: This is synchronous; preserve deterministic behavior for its direct
            callers.

            Change safety: Preserve path isolation, encoding, and persistence side effects;
            preserve exception and fallback behavior expected by callers.
            """
            messages: list[MailboxMessage] = []
            for path in sorted(inbox.glob("*.json")):
                # Skip lock files and temp files
                if path.name.startswith(".") or path.name.endswith(".tmp"):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    msg = MailboxMessage.from_dict(data)
                    if not unread_only or not msg.read:
                        messages.append(msg)
                except (json.JSONDecodeError, KeyError):
                    # Skip corrupted message files rather than crashing.
                    continue
            return messages

        # Offload blocking I/O to thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _read_all)

    async def mark_read(self, message_id: str) -> None:
        """Mark the message with *message_id* as read (in-place update).

        Integration: Called by ``_drain_mailbox``, ``poll_permission_response`` and collaborates
        with ``get_mailbox_dir``, ``_lock_path``, ``asyncio.get_event_loop``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O; retain lock scope and release behavior.

        Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
        exception and fallback behavior expected by callers.
        """
        inbox = self.get_mailbox_dir()
        lock_path = self._lock_path()

        def _mark_read() -> bool:
            """Mark read for the enclosing subsystem.

            Integration: Used as an internal helper or callback at this module boundary and
            collaborates with ``exclusive_file_lock``, ``inbox.glob``, ``path.name.startswith``.

            Concurrency: This is synchronous; preserve deterministic behavior for its direct
            callers; retain lock scope and release behavior.

            Change safety: Preserve path isolation, encoding, and persistence side effects;
            preserve exception and fallback behavior expected by callers.
            """
            with exclusive_file_lock(lock_path):
                for path in inbox.glob("*.json"):
                    # Skip lock files and temp files
                    if path.name.startswith(".") or path.name.endswith(".tmp"):
                        continue
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        continue

                    if data.get("id") == message_id:
                        data["read"] = True
                        tmp_path = path.with_suffix(".json.tmp")
                        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                        os.replace(tmp_path, path)
                        return True
                return False

        # Offload blocking I/O to thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _mark_read)

    async def clear(self) -> None:
        """Remove all message files from the inbox.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``get_mailbox_dir``, ``_lock_path``, ``asyncio.get_event_loop``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O; retain lock scope and release behavior.

        Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
        exception and fallback behavior expected by callers.
        """
        inbox = self.get_mailbox_dir()
        lock_path = self._lock_path()

        def _clear() -> None:
            """Clear mutable state owned by teammate mailbox.clear.

            Integration: Used as an internal helper or callback at this module boundary and
            collaborates with ``exclusive_file_lock``, ``inbox.glob``, ``path.name.startswith``.

            Concurrency: This is synchronous; preserve deterministic behavior for its direct
            callers; retain lock scope and release behavior.

            Change safety: Preserve path isolation, encoding, and persistence side effects;
            preserve exception and fallback behavior expected by callers.
            """
            with exclusive_file_lock(lock_path):
                for path in inbox.glob("*.json"):
                    # Skip lock files
                    if path.name.startswith("."):
                        continue
                    try:
                        path.unlink()
                    except OSError:
                        pass

        # Offload blocking I/O to thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _clear)


# ---------------------------------------------------------------------------
# Factory helpers (basic)
# ---------------------------------------------------------------------------


def _make_message(
    msg_type: MessageType,
    sender: str,
    recipient: str,
    payload: dict[str, Any],
) -> MailboxMessage:
    """Create message for the enclosing subsystem.

    Integration: Called by ``create_user_message``, ``create_shutdown_request`` and collaborates
    with ``MailboxMessage``, ``time.time``, ``uuid.uuid4``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return MailboxMessage(
        id=str(uuid.uuid4()),
        type=msg_type,
        sender=sender,
        recipient=recipient,
        payload=payload,
        timestamp=time.time(),
    )


def create_user_message(sender: str, recipient: str, content: str) -> MailboxMessage:
    """Create a plain text user message.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``_make_message``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return _make_message("user_message", sender, recipient, {"content": content})


def create_shutdown_request(sender: str, recipient: str) -> MailboxMessage:
    """Create a shutdown request message.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``_make_message``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return _make_message("shutdown", sender, recipient, {})


def create_idle_notification(
    sender: str, recipient: str, summary: str
) -> MailboxMessage:
    """Create an idle-notification message with a brief summary.

    Integration: Called by ``start_in_process_teammate`` and collaborates with
    ``_make_message``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return _make_message(
        "idle_notification", sender, recipient, {"summary": summary}
    )


# ---------------------------------------------------------------------------
# Permission message factory functions (matching TS teammateMailbox.ts)
# ---------------------------------------------------------------------------


def create_permission_request_message(
    sender: str,
    recipient: str,
    request_data: dict[str, Any],
) -> MailboxMessage:
    """Create a permission_request message from worker to leader.

    Args:
        sender: The sending worker's agent name.
        recipient: The recipient leader's agent name.
        request_data: Dict with keys: request_id, agent_id, tool_name,
            tool_use_id, description, input, permission_suggestions.

    Returns:
        A :class:`MailboxMessage` of type ``permission_request``.

    Integration: Called by ``send_permission_request_via_mailbox`` and collaborates with
    ``_make_message``, ``request_data.get``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    payload: dict[str, Any] = {
        "type": "permission_request",
        "request_id": request_data.get("request_id", ""),
        "agent_id": request_data.get("agent_id", sender),
        "tool_name": request_data.get("tool_name", ""),
        "tool_use_id": request_data.get("tool_use_id", ""),
        "description": request_data.get("description", ""),
        "input": request_data.get("input", {}),
        "permission_suggestions": request_data.get("permission_suggestions", []),
    }
    return _make_message("permission_request", sender, recipient, payload)


def create_permission_response_message(
    sender: str,
    recipient: str,
    response_data: dict[str, Any],
) -> MailboxMessage:
    """Create a permission_response message from leader to worker.

    Args:
        sender: The sending leader's agent name.
        recipient: The target worker's agent name.
        response_data: Dict with keys: request_id, subtype ('success'|'error'),
            error (optional), updated_input (optional), permission_updates (optional).

    Returns:
        A :class:`MailboxMessage` of type ``permission_response``.

    Integration: Called by ``send_permission_response_via_mailbox`` and collaborates with
    ``response_data.get``, ``_make_message``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    subtype = response_data.get("subtype", "success")
    if subtype == "error":
        payload: dict[str, Any] = {
            "type": "permission_response",
            "request_id": response_data.get("request_id", ""),
            "subtype": "error",
            "error": response_data.get("error", "Permission denied"),
        }
    else:
        payload = {
            "type": "permission_response",
            "request_id": response_data.get("request_id", ""),
            "subtype": "success",
            "response": {
                "updated_input": response_data.get("updated_input"),
                "permission_updates": response_data.get("permission_updates"),
            },
        }
    return _make_message("permission_response", sender, recipient, payload)


def create_sandbox_permission_request_message(
    sender: str,
    recipient: str,
    request_data: dict[str, Any],
) -> MailboxMessage:
    """Create a sandbox_permission_request message from worker to leader.

    Args:
        sender: The sending worker's agent name.
        recipient: The recipient leader's agent name.
        request_data: Dict with keys: requestId, workerId, workerName,
            workerColor (optional), host.

    Returns:
        A :class:`MailboxMessage` of type ``sandbox_permission_request``.

    Integration: Called by ``send_sandbox_permission_request_via_mailbox`` and collaborates with
    ``_make_message``, ``request_data.get``, ``time.time``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    payload: dict[str, Any] = {
        "type": "sandbox_permission_request",
        "requestId": request_data.get("requestId", ""),
        "workerId": request_data.get("workerId", sender),
        "workerName": request_data.get("workerName", sender),
        "workerColor": request_data.get("workerColor"),
        "hostPattern": {"host": request_data.get("host", "")},
        "createdAt": int(time.time() * 1000),
    }
    return _make_message("sandbox_permission_request", sender, recipient, payload)


def create_sandbox_permission_response_message(
    sender: str,
    recipient: str,
    response_data: dict[str, Any],
) -> MailboxMessage:
    """Create a sandbox_permission_response message from leader to worker.

    Args:
        sender: The sending leader's agent name.
        recipient: The target worker's agent name.
        response_data: Dict with keys: requestId, host, allow.

    Returns:
        A :class:`MailboxMessage` of type ``sandbox_permission_response``.

    Integration: Called by ``send_sandbox_permission_response_via_mailbox`` and collaborates
    with ``_make_message``, ``response_data.get``, ``strftime``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    from datetime import datetime, timezone

    payload: dict[str, Any] = {
        "type": "sandbox_permission_response",
        "requestId": response_data.get("requestId", ""),
        "host": response_data.get("host", ""),
        "allow": bool(response_data.get("allow", False)),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    return _make_message("sandbox_permission_response", sender, recipient, payload)


# ---------------------------------------------------------------------------
# Type-guard helpers (matching TS isPermissionRequest etc.)
# ---------------------------------------------------------------------------


def is_permission_request(msg: MailboxMessage) -> dict[str, Any] | None:
    """Return the permission request payload if *msg* is a permission_request, else None.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``msg.payload.get``, ``json.loads``, ``parsed.get``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if msg.type == "permission_request":
        return msg.payload
    # Also check text field for compatibility with text-envelope messages
    text = msg.payload.get("text", "")
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("type") == "permission_request":
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def is_permission_response(msg: MailboxMessage) -> dict[str, Any] | None:
    """Return the permission response payload if *msg* is a permission_response, else None.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``msg.payload.get``, ``json.loads``, ``parsed.get``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if msg.type == "permission_response":
        return msg.payload
    text = msg.payload.get("text", "")
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("type") == "permission_response":
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def is_sandbox_permission_request(msg: MailboxMessage) -> dict[str, Any] | None:
    """Return payload if *msg* is a sandbox_permission_request, else None.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``msg.payload.get``, ``json.loads``, ``parsed.get``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if msg.type == "sandbox_permission_request":
        return msg.payload
    text = msg.payload.get("text", "")
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("type") == "sandbox_permission_request":
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def is_sandbox_permission_response(msg: MailboxMessage) -> dict[str, Any] | None:
    """Return payload if *msg* is a sandbox_permission_response, else None.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``msg.payload.get``, ``json.loads``, ``parsed.get``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if msg.type == "sandbox_permission_response":
        return msg.payload
    text = msg.payload.get("text", "")
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("type") == "sandbox_permission_response":
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


# ---------------------------------------------------------------------------
# Global mailbox convenience functions (matching TS writeToMailbox etc.)
# ---------------------------------------------------------------------------


async def write_to_mailbox(
    recipient_name: str,
    message: dict[str, Any],
    team_name: str | None = None,
) -> None:
    """Write a TeammateMessage-format dict to a recipient's mailbox.

    This mirrors the TS ``writeToMailbox(recipientName, message, teamName)``
    function.  The *message* dict should have at minimum a ``from`` key and
    a ``text`` key (the serialised message content), and optionally
    ``timestamp``, ``color``, and ``summary``.

    Args:
        recipient_name: The recipient agent's name/id.
        message: Dict with ``from``, ``text``, and optional fields.
        team_name: Optional team name; defaults to ``CLAUDE_CODE_TEAM_NAME``
            env var, then ``"default"``.

    Integration: Called by ``send_permission_request_via_mailbox``,
    ``send_permission_response_via_mailbox`` and collaborates with ``message.get``,
    ``MailboxMessage``, ``TeammateMailbox``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    team = team_name or os.environ.get("CLAUDE_CODE_TEAM_NAME", "default")
    text = message.get("text", "")

    # Detect message type from serialised text content so routing works
    msg_type: MessageType = "user_message"
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "type" in parsed:
            t = parsed["type"]
            if t in (
                "permission_request",
                "permission_response",
                "sandbox_permission_request",
                "sandbox_permission_response",
                "shutdown",
                "idle_notification",
            ):
                msg_type = t  # type: ignore[assignment]
    except (json.JSONDecodeError, TypeError):
        pass

    msg = MailboxMessage(
        id=str(uuid.uuid4()),
        type=msg_type,
        sender=message.get("from", "unknown"),
        recipient=recipient_name,
        payload={
            "text": text,
            "color": message.get("color"),
            "summary": message.get("summary"),
            "timestamp": message.get("timestamp"),
        },
        timestamp=time.time(),
    )
    mailbox = TeammateMailbox(team, recipient_name)
    await mailbox.write(msg)
