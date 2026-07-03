"""Session routing for ohmo gateway.

Integration: This ohmo module specializes the reusable OpenHarness runtime with personal
workspace, memory, session, gateway, or channel behavior; core modules must not depend on it.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve the ohmo workspace boundary, conversation/session isolation, attachment
and channel contracts, credential redaction, and cleanup of per-session runtimes.
"""

from __future__ import annotations

from openharness.channels.bus.events import InboundMessage


def session_key_for_message(message: InboundMessage) -> str:
    """Route sessions by chat, isolating shared chats by thread/sender.

    Private chats keep the original ``channel:chat_id`` key so existing long
    ohmo sessions remain resumable. Group/shared chats include sender identity
    to avoid multiple people sharing one agent memory.

    Integration: Called by ``OhmoGatewayBridge.run`` and collaborates with ``lower``, ``strip``,
    ``message.metadata.get``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if message.session_key_override:
        return message.session_key_override
    sender_id = str(message.sender_id).strip() or "anonymous"
    chat_type = str(message.metadata.get("chat_type") or "").strip().lower()
    is_shared_chat = chat_type in {"group", "chat", "supergroup", "channel", "room"}
    thread_id = (
        message.metadata.get("thread_id")
        or message.metadata.get("thread_ts")
        or message.metadata.get("message_thread_id")
    )
    if thread_id:
        if is_shared_chat:
            return f"{message.channel}:{message.chat_id}:{thread_id}:{sender_id}"
        return f"{message.channel}:{message.chat_id}:{thread_id}"
    if is_shared_chat:
        return f"{message.channel}:{message.chat_id}:{sender_id}"
    return f"{message.channel}:{message.chat_id}"
