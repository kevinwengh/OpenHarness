"""Chat channel implementations.

Integration: This module participates in chat transport adapters and normalized inbound/outbound
message flow.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve authorization and mentions, attachment bounds, SDK task lifecycle,
reconnect/backoff, rate limits, and credential redaction.
"""

from openharness.channels.impl.base import BaseChannel
from openharness.channels.impl.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
