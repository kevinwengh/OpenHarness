"""Convert admitted channel messages into bounded generic automation events."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from openharness.automation.models import AutomationEvent
from openharness.channels.bus.events import InboundMessage

_SAFE_EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


def bounded_event_ancestry(*values: object) -> list[str]:
    """Normalize, de-duplicate, and cap loop-prevention ancestry.

    Platform adapters may round-trip automation metadata more than once. Stable
    de-duplication keeps such messages valid under ``AutomationEvent``'s unique
    ancestry contract while retaining the most recent sixteen identities.
    """

    normalized: list[str] = []
    for value in values:
        item = str(value).strip()[:256]
        if item and item not in normalized:
            normalized.append(item)
    return normalized[-16:]


def channel_message_event(message: InboundMessage) -> AutomationEvent:
    """Return a sanitized event for a message already admitted by its channel adapter."""

    metadata = message.metadata if isinstance(message.metadata, dict) else {}
    channel_metadata = metadata.get(message.channel)
    channel_metadata = channel_metadata if isinstance(channel_metadata, dict) else {}
    raw_event = channel_metadata.get("event")
    raw_event = raw_event if isinstance(raw_event, dict) else {}

    thread_id = _first_string(
        metadata.get("thread_id"),
        metadata.get("thread_ts"),
        channel_metadata.get("thread_ts"),
        raw_event.get("thread_ts"),
    )
    message_id = _first_string(
        metadata.get("message_id"),
        metadata.get("event_id"),
        raw_event.get("client_msg_id"),
        raw_event.get("event_ts"),
        raw_event.get("ts"),
    )
    occurred_at = _utc_timestamp(message.timestamp)
    source_id = message_id or _fallback_source_id(message, occurred_at)
    event_id = _event_id(message.channel, source_id)

    automation_marker = metadata.get("_automation")
    automation_marker = automation_marker if isinstance(automation_marker, dict) else {}
    ancestry = automation_marker.get("ancestry")
    if not isinstance(ancestry, list):
        ancestry = []
    ancestry = bounded_event_ancestry(*ancestry)

    safe_metadata = {
        key: value
        for key, value in {
            "chat_type": _first_string(metadata.get("chat_type")),
            "channel_type": _first_string(channel_metadata.get("channel_type")),
            "event_type": _first_string(raw_event.get("type")),
        }.items()
        if value is not None
    }
    return AutomationEvent(
        id=event_id,
        type="channel.message",
        occurred_at=occurred_at,
        source={
            "adapter": "channel",
            "channel": message.channel,
            "account": _first_string(metadata.get("account"), limit=128),
            "instance": _first_string(metadata.get("instance"), limit=128),
        },
        actor={
            "id": str(message.sender_id)[:256],
            "display_name": _first_string(metadata.get("sender_name"), limit=256),
        },
        subject={
            "chat_id": str(message.chat_id)[:512],
            "thread_id": thread_id,
            "message_id": message_id,
        },
        payload={
            "text": message.content,
            "attachments": [_attachment_description(item) for item in message.media[:32]],
        },
        metadata=safe_metadata,
        automation_generated=bool(automation_marker.get("generated")),
        ancestry=ancestry,
    )


def _utc_timestamp(value: datetime) -> datetime:
    """Normalize an inbound message timestamp to UTC."""

    return value.astimezone(timezone.utc)


def _first_string(*values, limit: int = 512) -> str | None:
    """Return the first non-blank string bounded for persisted event state."""

    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()[:limit]
    return None


def _event_id(channel: str, source_id: str) -> str:
    """Keep a safe platform ID readable or hash an unsafe composite identity."""

    candidate = f"{channel}:{source_id}"
    if _SAFE_EVENT_ID.fullmatch(candidate):
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8", errors="replace")).hexdigest()
    return f"channel:{digest}"


def _fallback_source_id(message: InboundMessage, occurred_at: datetime) -> str:
    """Derive a deterministic delivery identity when the adapter provides none."""

    content = "\0".join(
        (
            message.channel,
            str(message.chat_id),
            str(message.sender_id),
            occurred_at.isoformat(),
            message.content,
        )
    )
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def _attachment_description(reference: str) -> dict[str, str]:
    """Persist only a bounded filename and scheme, never signed URL details."""

    parsed = urlsplit(str(reference))
    if parsed.scheme and parsed.netloc:
        name = Path(parsed.path).name or "attachment"
        return {"name": name[:256], "kind": parsed.scheme[:32]}
    return {"name": Path(str(reference)).name[:256] or "attachment", "kind": "file"}
