"""API error types for OpenHarness.

Integration: This module participates in provider streaming clients and normalized request/event
contracts.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve request conversion, streamed tool calls, usage/errors, auth secrecy,
retries, and multi-turn replay.
"""

from __future__ import annotations


class OpenHarnessApiError(RuntimeError):
    """Base class for upstream API failures.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """


class AuthenticationFailure(OpenHarnessApiError):
    """Raised when the upstream service rejects the provided credentials.

    Integration: Constructed or referenced by ``_translate_api_error``, ``_extract_account_id``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """


class RateLimitFailure(OpenHarnessApiError):
    """Raised when the upstream service rejects the request due to rate limits.

    Integration: Constructed or referenced by ``_translate_api_error``,
    ``_translate_status_error``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """


class RequestFailure(OpenHarnessApiError):
    """Raised for generic request or transport failures.

    Integration: Constructed or referenced by ``AnthropicApiClient.stream_message``,
    ``_translate_api_error``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """
