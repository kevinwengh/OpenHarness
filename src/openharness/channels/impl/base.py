"""Base channel interface for chat platforms.

Integration: This module participates in chat transport adapters and normalized inbound/outbound
message flow.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve authorization and mentions, attachment bounds, SDK task lifecycle,
reconnect/backoff, rate limits, and credential redaction.
"""

import os
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from openharness.channels.bus.events import InboundMessage, OutboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.config.paths import get_data_dir

logger = logging.getLogger(__name__)


def resolve_channel_media_dir(channel_name: str) -> Path:
    """Return the local download directory for inbound channel media.

    Integration: Called by ``DiscordChannel._handle_message_create``,
    ``FeishuChannel._download_and_save_media`` and collaborates with ``os.environ.get``,
    ``media_dir.mkdir``, ``resolve``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    custom_root = os.environ.get("OPENHARNESS_CHANNEL_MEDIA_DIR")
    if custom_root:
        root = Path(custom_root).expanduser().resolve()
    else:
        ohmo_workspace = os.environ.get("OHMO_WORKSPACE")
        if ohmo_workspace:
            from ohmo.workspace import get_attachments_dir

            root = get_attachments_dir(ohmo_workspace)
        else:
            root = get_data_dir() / "media"
    media_dir = root / channel_name
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir


class BaseChannel(ABC):
    """Abstract base class for chat channel implementations.

    Each channel (Telegram, Discord, etc.) should implement this interface
    to integrate with the nanobot message bus.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Event loop: Async methods ``start``, ``stop``, ``send``, ``_handle_message`` run on their
    caller's loop; instances must retain clear task, cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    name: str = "base"

    def __init__(self, config: Any, bus: MessageBus):
        """Initialize the channel.

        Args:
            config: Channel-specific configuration.
            bus: The message bus for communication.

        Integration: Used as an internal helper or callback at this module boundary.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.config = config
        self.bus = bus
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """Start the channel and begin listening for messages.

        This should be a long-running async task that:
        1. Connects to the chat platform
        2. Listens for incoming messages
        3. Forwards messages to the bus via _handle_message()

        Integration: Exposed as a public entrypoint for this subsystem.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up resources.

        Integration: Exposed as a public entrypoint for this subsystem.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through this channel.

        Args:
            msg: The message to send.

        Integration: Exposed as a public entrypoint for this subsystem.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        pass

    def is_allowed(self, sender_id: str) -> bool:
        """Check if *sender_id* is permitted.  Empty list → deny all; ``"*"`` → allow all.

        Integration: Called by ``BaseChannel._handle_message``,
        ``DiscordChannel._handle_message_create`` and collaborates with ``logger.warning``,
        ``any``, ``sender_str.split``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list:
            logger.warning("%s: allow_from is empty — all access denied", self.name)
            return False
        if "*" in allow_list:
            return True
        sender_str = str(sender_id)
        return sender_str in allow_list or any(
            p in allow_list for p in sender_str.split("|") if p
        )

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> None:
        """Handle an incoming message from the chat platform.

        This method checks permissions and forwards to the bus.

        Args:
            sender_id: The sender's identifier.
            chat_id: The chat/channel identifier.
            content: Message text content.
            media: Optional list of media URLs.
            metadata: Optional channel-specific metadata.
            session_key: Optional session key override (e.g. thread-scoped sessions).

        Integration: Called by ``DingTalkChannel._on_message``,
        ``DiscordChannel._handle_message_create`` and collaborates with ``InboundMessage``,
        ``is_allowed``, ``logger.warning``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if not self.is_allowed(sender_id):
            logger.warning(
                "Access denied for sender %s on channel %s. "
                "Add them to allowFrom list in config to grant access.",
                sender_id, self.name,
            )
            return

        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            media=media or [],
            metadata=metadata or {},
            session_key_override=session_key,
        )

        await self.bus.publish_inbound(msg)

    @property
    def is_running(self) -> bool:
        """Check if the channel is running.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self._running
