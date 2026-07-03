"""ChannelBridge: connects the MessageBus to a QueryEngine instance.

Usage::

    bridge = ChannelBridge(engine=query_engine, bus=message_bus)
    asyncio.create_task(bridge.run())

The bridge continuously consumes inbound messages from the bus, feeds them
to QueryEngine.submit_message(), and publishes the assembled reply as an
OutboundMessage back to the bus for delivery by ChannelManager.

Integration: This module participates in chat transport adapters and normalized inbound/outbound
message flow.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve authorization and mentions, attachment bounds, SDK task lifecycle,
reconnect/backoff, rate limits, and credential redaction.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from openharness.channels.bus.events import InboundMessage, OutboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.engine.stream_events import AssistantTextDelta, AssistantTurnComplete

if TYPE_CHECKING:
    from openharness.engine.query_engine import QueryEngine

logger = logging.getLogger(__name__)


class ChannelBridge:
    """Bridges inbound channel messages to the QueryEngine and routes replies back.

    One bridge instance should be created per QueryEngine.  It owns the asyncio
    loop integration and handles back-pressure through the MessageBus queues.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Event loop: Async methods ``start``, ``stop``, ``run``, ``_loop`` run on their caller's
    loop; instances must retain clear task, cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self, *, engine: "QueryEngine", bus: MessageBus) -> None:
        """Initialize ``ChannelBridge`` and bind its runtime dependencies.

        Integration: Exposed through ``ChannelBridge``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._engine = engine
        self._bus = bus
        self._running = False
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the bridge loop as a background task.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``asyncio.create_task``, ``logger.info``, ``_loop``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="channel-bridge")
        logger.info("ChannelBridge started")

    async def stop(self) -> None:
        """Stop the bridge loop gracefully.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``logger.info``, ``_task.cancel``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("ChannelBridge stopped")

    async def run(self) -> None:
        """Run the bridge inline (blocks until stopped or cancelled).

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``_loop``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._running = True
        try:
            await self._loop()
        finally:
            self._running = False

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Main processing loop: consume → process → publish.

        Integration: Called by ``ChannelBridge.start``, ``ChannelBridge.run`` and collaborates
        with ``asyncio.wait_for``, ``_handle``, ``logger.exception``.

        Event loop: This coroutine coordinates child tasks; preserve cancellation, completion,
        and exception ownership.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self._bus.consume_inbound(),
                    timeout=1.0,
                )
                await self._handle(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("ChannelBridge: unhandled error processing message")

    async def _handle(self, msg: InboundMessage) -> None:
        """Process one inbound message and publish the reply.

        Integration: Called by ``ChannelBridge._loop`` and collaborates with ``logger.debug``,
        ``strip``, ``OutboundMessage``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        logger.debug("ChannelBridge received from %s/%s", msg.channel, msg.chat_id)

        reply_parts: list[str] = []
        try:
            async for event in self._engine.submit_message(msg.content):
                if isinstance(event, AssistantTextDelta):
                    reply_parts.append(event.text)
                elif isinstance(event, AssistantTurnComplete):
                    # Turn is done; we'll send the accumulated text below
                    pass
        except Exception:
            logger.exception(
                "ChannelBridge: engine error for message from %s/%s",
                msg.channel,
                msg.chat_id,
            )
            reply_parts = ["[Error: failed to process your message]"]

        reply_text = "".join(reply_parts).strip()
        if not reply_text:
            logger.debug("ChannelBridge: empty reply, skipping publish")
            return

        outbound = OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=reply_text,
            metadata={"_session_key": msg.session_key},
        )
        await self._bus.publish_outbound(outbound)
        logger.debug(
            "ChannelBridge published reply to %s/%s (%d chars)",
            msg.channel,
            msg.chat_id,
            len(reply_text),
        )
