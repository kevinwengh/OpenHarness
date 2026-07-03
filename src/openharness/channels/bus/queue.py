"""Async message queue for decoupled channel-agent communication.

Integration: This module participates in chat transport adapters and normalized inbound/outbound
message flow.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve authorization and mentions, attachment bounds, SDK task lifecycle,
reconnect/backoff, rate limits, and credential redaction.
"""

import asyncio

from openharness.channels.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.

    Integration: Constructed or referenced by ``OhmoGatewayService.__init__``.

    Event loop: Async methods ``publish_inbound``, ``consume_inbound``, ``publish_outbound``,
    ``consume_outbound`` run on their caller's loop; instances must retain clear task,
    cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self):
        """Initialize ``MessageBus`` and bind its runtime dependencies.

        Integration: Exposed through ``MessageBus`` and collaborates with ``asyncio.Queue``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent.

        Integration: Called by ``BaseChannel._handle_message`` and collaborates with
        ``inbound.put``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available).

        Integration: Called by ``OhmoGatewayBridge.run``, ``ChannelBridge._loop`` and
        collaborates with ``inbound.get``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels.

        Integration: Called by ``OhmoGatewayBridge._handle_stop``,
        ``OhmoGatewayBridge._handle_restart`` and collaborates with ``outbound.put``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available).

        Integration: Called by ``ChannelManager._dispatch_outbound`` and collaborates with
        ``outbound.get``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``inbound.qsize``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``outbound.qsize``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        return self.outbound.qsize()
