"""Message bus module for decoupled channel-agent communication.

Integration: This module participates in chat transport adapters and normalized inbound/outbound
message flow.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve authorization and mentions, attachment bounds, SDK task lifecycle,
reconnect/backoff, rate limits, and credential redaction.
"""

from openharness.channels.bus.events import InboundMessage, OutboundMessage
from openharness.channels.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
