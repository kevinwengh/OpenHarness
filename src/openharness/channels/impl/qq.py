"""QQ channel implementation using botpy SDK.

Integration: This module participates in chat transport adapters and normalized inbound/outbound
message flow.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve authorization and mentions, attachment bounds, SDK task lifecycle,
reconnect/backoff, rate limits, and credential redaction.
"""

import asyncio
import logging
from collections import deque
from typing import TYPE_CHECKING


from openharness.channels.bus.events import OutboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.channels.impl.base import BaseChannel
from openharness.config.schema import QQConfig

logger = logging.getLogger(__name__)

try:
    import botpy
    from botpy.message import C2CMessage

    QQ_AVAILABLE = True
except ImportError:
    QQ_AVAILABLE = False
    botpy = None
    C2CMessage = None

if TYPE_CHECKING:
    from botpy.message import C2CMessage


def _make_bot_class(channel: "QQChannel") -> "type[botpy.Client]":
    """Create a botpy Client subclass bound to the given channel.

    Integration: Called by ``QQChannel.start`` and collaborates with ``botpy.Intents``,
    ``__init__``, ``logger.info``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    intents = botpy.Intents(public_messages=True, direct_message=True)

    class _Bot(botpy.Client):
        """Coordinate the bot responsibilities for this subsystem.

        Integration: Owned by the enclosing module and consumed through its public methods.

        Event loop: Async methods ``on_ready``, ``on_c2c_message_create``,
        ``on_direct_message_create`` run on their caller's loop; instances must retain clear
        task, cancellation, and cleanup ownership.

        Change safety: Preserve constructor invariants, public method contracts, state
        ownership, and cleanup expectations used by collaborators.
        """
        def __init__(self):
            # Disable botpy's file log — not using loguru; default "botpy.log" fails on read-only fs
            """Initialize ``_make_bot_class._Bot`` and bind its runtime dependencies.

            Integration: Exposed through ``_make_bot_class._Bot``.

            Concurrency: This is synchronous; preserve deterministic behavior for its direct
            callers.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            super().__init__(intents=intents, ext_handlers=False)

        async def on_ready(self):
            """Handle the ready lifecycle event.

            Integration: Exposed as a public entrypoint for this subsystem and collaborates with
            ``logger.info``.

            Event loop: This coroutine executes synchronously until it returns; filesystem or
            process work therefore runs inline on the caller's loop. Keep that work bounded or
            offload it before it can block.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            logger.info("QQ bot ready: %s", self.robot.name)

        async def on_c2c_message_create(self, message: "C2CMessage"):
            """Handle the c2c message create lifecycle event.

            Integration: Exposed as a public entrypoint for this subsystem and collaborates with
            ``channel._on_message``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await channel._on_message(message)

        async def on_direct_message_create(self, message):
            """Handle the direct message create lifecycle event.

            Integration: Exposed as a public entrypoint for this subsystem and collaborates with
            ``channel._on_message``.

            Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
            blocking I/O.

            Change safety: Preserve the signature, return value, and side-effect contract
            expected by callers.
            """
            await channel._on_message(message)

    return _Bot


class QQChannel(BaseChannel):
    """QQ channel using botpy SDK with WebSocket connection.

    Integration: Constructed or referenced by ``ChannelManager._init_channels``.

    Event loop: Async methods ``start``, ``_run_bot``, ``stop``, ``send`` run on their caller's
    loop; instances must retain clear task, cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    name = "qq"

    def __init__(self, config: QQConfig, bus: MessageBus):
        """Initialize ``QQChannel`` and bind its runtime dependencies.

        Integration: Exposed through ``QQChannel`` and collaborates with ``deque``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        super().__init__(config, bus)
        self.config: QQConfig = config
        self._client: "botpy.Client | None" = None
        self._processed_ids: deque = deque(maxlen=1000)
        self._msg_seq: int = 1  # 消息序列号，避免被 QQ API 去重

    async def start(self) -> None:
        """Start the QQ bot.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_make_bot_class``, ``BotClass``, ``logger.info``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if not QQ_AVAILABLE:
            logger.error("QQ SDK not installed. Run: pip install qq-botpy")
            return

        if not self.config.app_id or not self.config.secret:
            logger.error("QQ app_id and secret not configured")
            return

        self._running = True
        BotClass = _make_bot_class(self)
        self._client = BotClass()

        logger.info("QQ bot started (C2C private message)")
        await self._run_bot()

    async def _run_bot(self) -> None:
        """Run the bot connection with auto-reconnect.

        Integration: Called by ``QQChannel.start`` and collaborates with ``logger.info``,
        ``_client.start``, ``logger.warning``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        while self._running:
            try:
                await self._client.start(appid=self.config.app_id, secret=self.config.secret)
            except Exception as e:
                logger.warning("QQ bot error: %s", e)
            if self._running:
                logger.info("Reconnecting QQ bot in 5 seconds...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the QQ bot.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``logger.info``, ``_client.close``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        self._running = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        logger.info("QQ bot stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through QQ.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``logger.warning``, ``msg.metadata.get``, ``_client.api.post_c2c_message``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        if not self._client:
            logger.warning("QQ client not initialized")
            return
        try:
            msg_id = msg.metadata.get("message_id")
            self._msg_seq += 1  # 递增序列号
            await self._client.api.post_c2c_message(
                openid=msg.chat_id,
                msg_type=0,
                content=msg.content,
                msg_id=msg_id,
                msg_seq=self._msg_seq,  # 添加序列号避免去重
            )
        except Exception as e:
            logger.error("Error sending QQ message: %s", e)

    async def _on_message(self, data: "C2CMessage") -> None:
        """Handle incoming message from QQ.

        Integration: Used as an internal helper or callback at this module boundary and
        collaborates with ``_processed_ids.append``, ``strip``, ``_handle_message``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        try:
            # Dedup by message ID
            if data.id in self._processed_ids:
                return
            self._processed_ids.append(data.id)

            author = data.author
            user_id = str(getattr(author, 'id', None) or getattr(author, 'user_openid', 'unknown'))
            content = (data.content or "").strip()
            if not content:
                return

            await self._handle_message(
                sender_id=user_id,
                chat_id=user_id,
                content=content,
                metadata={"message_id": data.id},
            )
        except Exception:
            logger.exception("Error handling QQ message")
