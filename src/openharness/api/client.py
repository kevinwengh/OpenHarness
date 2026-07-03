"""Anthropic API client wrapper with retry logic.

Integration: This module participates in provider streaming clients and normalized request/event
contracts.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve request conversion, streamed tool calls, usage/errors, auth secrecy,
retries, and multi-turn replay.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Protocol

from anthropic import APIError, APIStatusError, AsyncAnthropic

from openharness.api.errors import (
    AuthenticationFailure,
    OpenHarnessApiError,
    RateLimitFailure,
    RequestFailure,
)
from openharness.auth.external import (
    claude_attribution_header,
    claude_oauth_betas,
    claude_oauth_headers,
    get_claude_code_session_id,
)
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage, assistant_message_from_api

log = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds
MAX_DELAY = 30.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
OAUTH_BETA_HEADER = "oauth-2025-04-20"


@dataclass(frozen=True)
class ApiMessageRequest:
    """Input parameters for a model invocation.

    Integration: Constructed or referenced by ``CopilotClient.stream_message``, ``run_query``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    model: str
    messages: list[ConversationMessage]
    system_prompt: str | None = None
    max_tokens: int = 4096
    tools: list[dict[str, Any]] = field(default_factory=list)
    effort: str | None = None


@dataclass(frozen=True)
class ApiTextDeltaEvent:
    """Incremental text produced by the model.

    Integration: Constructed or referenced by ``AnthropicApiClient._stream_once``,
    ``CodexApiClient._stream_once``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    text: str


@dataclass(frozen=True)
class ApiMessageCompleteEvent:
    """Terminal event containing the full assistant message.

    Integration: Constructed or referenced by ``AnthropicApiClient._stream_once``,
    ``CodexApiClient._stream_once``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    message: ConversationMessage
    usage: UsageSnapshot
    stop_reason: str | None = None


@dataclass(frozen=True)
class ApiRetryEvent:
    """A recoverable upstream failure that will be retried automatically.

    Integration: Constructed or referenced by ``AnthropicApiClient.stream_message``,
    ``CodexApiClient.stream_message``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    message: str
    attempt: int
    max_attempts: int
    delay_seconds: float


ApiStreamEvent = ApiTextDeltaEvent | ApiMessageCompleteEvent | ApiRetryEvent


class SupportsStreamingMessages(Protocol):
    """Protocol used by the query engine in tests and production.

    Integration: Implemented by injected adapters and consumed through structural typing.

    Event loop: Async methods ``stream_message`` run on their caller's loop; instances must
    retain clear task, cancellation, and cleanup ownership.

    Change safety: Update every implementation, injection site, and contract test when method
    signatures or ownership expectations change.
    """

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """Stream one provider response as normalized API events.

        Integration: Exposed as a public entrypoint for this subsystem.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.

        Provider contract: Preserve request translation for system prompts, messages, images,
        tool schemas, reasoning effort, and output limits; preserve streamed text/reasoning and
        incremental tool-call identifiers and arguments; emit one normalized final message with
        usage; translate auth, timeout, rate-limit, malformed-stream, and retry failures without
        exposing credentials. Any change must also verify multi-turn assistant tool-call replay
        followed by matching tool results.
        """


def _is_retryable(exc: Exception) -> bool:
    """Check if an exception is retryable.

    Integration: Used as an internal helper or callback at this module boundary.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if isinstance(exc, APIStatusError):
        return exc.status_code in RETRYABLE_STATUS_CODES
    if isinstance(exc, APIError):
        return True  # Network errors are retryable
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    return False


def _get_retry_delay(attempt: int, exc: Exception | None = None) -> float:
    """Calculate delay with exponential backoff and jitter.

    Integration: Called by ``test_api_retry_config``, ``AnthropicApiClient.stream_message`` and
    collaborates with ``random.uniform``, ``retry_after.get``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    import random

    # Check for Retry-After header
    if isinstance(exc, APIStatusError):
        retry_after = getattr(exc, "headers", {})
        if hasattr(retry_after, "get"):
            val = retry_after.get("retry-after")
            if val:
                try:
                    return min(float(val), MAX_DELAY)
                except (ValueError, TypeError):
                    pass

    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
    jitter = random.uniform(0, delay * 0.25)
    return delay + jitter


class AnthropicApiClient:
    """Thin wrapper around the Anthropic async SDK with retry logic.

    Integration: Constructed or referenced by ``_run``, ``_resolve_api_client_from_settings``.

    Event loop: Async methods ``close``, ``stream_message``, ``_stream_once`` run on their
    caller's loop; instances must retain clear task, cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        auth_token: str | None = None,
        base_url: str | None = None,
        claude_oauth: bool = False,
        auth_token_resolver: Callable[[], str] | None = None,
    ) -> None:
        """Initialize ``AnthropicApiClient`` and bind its runtime dependencies.

        Integration: Exposed through ``AnthropicApiClient`` and collaborates with
        ``_create_client``, ``get_claude_code_session_id``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._api_key = api_key
        self._auth_token = auth_token
        self._base_url = base_url
        self._claude_oauth = claude_oauth
        self._auth_token_resolver = auth_token_resolver
        self._session_id = get_claude_code_session_id() if claude_oauth else ""
        self._client = self._create_client()

    def _create_client(self) -> AsyncAnthropic:
        """Create client for the enclosing subsystem.

        Integration: Called by ``AnthropicApiClient.__init__``,
        ``AnthropicApiClient._refresh_client_auth`` and collaborates with ``AsyncAnthropic``,
        ``claude_oauth_headers``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        kwargs: dict[str, Any] = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._auth_token:
            kwargs["auth_token"] = self._auth_token
            kwargs["default_headers"] = (
                claude_oauth_headers()
                if self._claude_oauth
                else {"anthropic-beta": OAUTH_BETA_HEADER}
            )
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return AsyncAnthropic(**kwargs)

    async def close(self) -> None:
        """Close the underlying HTTP client.

        Integration: Exposed as a public entrypoint for this subsystem.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        await self._client.close()

    def _refresh_client_auth(self) -> None:
        """Refresh client auth for the enclosing subsystem.

        Integration: Called by ``AnthropicApiClient.stream_message`` and collaborates with
        ``_auth_token_resolver``, ``_create_client``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if not self._claude_oauth or self._auth_token_resolver is None:
            return
        next_token = self._auth_token_resolver()
        if next_token and next_token != self._auth_token:
            self._auth_token = next_token
            self._client = self._create_client()

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """Stream one provider response as normalized API events.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``RequestFailure``, ``_refresh_client_auth``, ``_stream_once``.

        Event loop: This async generator preserves streamed ordering and caller-driven
        cancellation.

        Change safety: Preserve yield ordering and partial-consumption behavior; preserve
        exception and fallback behavior expected by callers.

        Provider contract: Preserve request translation for system prompts, messages, images,
        tool schemas, reasoning effort, and output limits; preserve streamed text/reasoning and
        incremental tool-call identifiers and arguments; emit one normalized final message with
        usage; translate auth, timeout, rate-limit, malformed-stream, and retry failures without
        exposing credentials. Any change must also verify multi-turn assistant tool-call replay
        followed by matching tool results.
        """
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                self._refresh_client_auth()
                async for event in self._stream_once(request):
                    yield event
                return  # Success
            except OpenHarnessApiError:
                raise  # Auth errors are not retried
            except Exception as exc:
                last_error = exc
                if attempt >= MAX_RETRIES or not _is_retryable(exc):
                    if isinstance(exc, APIError):
                        raise _translate_api_error(exc) from exc
                    raise RequestFailure(str(exc)) from exc

                delay = _get_retry_delay(attempt, exc)
                status = getattr(exc, "status_code", "?")
                log.warning(
                    "API request failed (attempt %d/%d, status=%s), retrying in %.1fs: %s",
                    attempt + 1, MAX_RETRIES + 1, status, delay, exc,
                )
                yield ApiRetryEvent(
                    message=str(exc),
                    attempt=attempt + 1,
                    max_attempts=MAX_RETRIES + 1,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)

        if last_error is not None:
            if isinstance(last_error, APIError):
                raise _translate_api_error(last_error) from last_error
            raise RequestFailure(str(last_error)) from last_error

    async def _stream_once(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """Perform one underlying provider streaming attempt.

        Integration: Used as an internal helper or callback at this module boundary and
        collaborates with ``claude_attribution_header``, ``claude_oauth_betas``,
        ``ApiMessageCompleteEvent``.

        Event loop: This async generator preserves streamed ordering and caller-driven
        cancellation.

        Change safety: Preserve yield ordering and partial-consumption behavior; preserve
        exception and fallback behavior expected by callers.

        Provider contract: Preserve request translation for system prompts, messages, images,
        tool schemas, reasoning effort, and output limits; preserve streamed text/reasoning and
        incremental tool-call identifiers and arguments; emit one normalized final message with
        usage; translate auth, timeout, rate-limit, malformed-stream, and retry failures without
        exposing credentials. Any change must also verify multi-turn assistant tool-call replay
        followed by matching tool results.
        """
        params: dict[str, Any] = {
            "model": request.model,
            "messages": [message.to_api_param() for message in request.messages],
            "max_tokens": request.max_tokens,
        }
        if request.system_prompt:
            params["system"] = request.system_prompt
        if self._claude_oauth:
            attribution = claude_attribution_header()
            params["system"] = (
                f"{attribution}\n{params['system']}"
                if params.get("system")
                else attribution
            )
        if request.tools:
            params["tools"] = request.tools
        if self._claude_oauth:
            params["betas"] = claude_oauth_betas()
            params["metadata"] = {
                "user_id": json.dumps(
                    {
                        "device_id": "openharness",
                        "session_id": self._session_id,
                        "account_uuid": "",
                    },
                    separators=(",", ":"),
                )
            }
            params["extra_headers"] = {"x-client-request-id": str(uuid.uuid4())}

        try:
            stream_api = self._client.beta.messages if self._claude_oauth else self._client.messages
            async with stream_api.stream(**params) as stream:
                async for event in stream:
                    if getattr(event, "type", None) != "content_block_delta":
                        continue
                    delta = getattr(event, "delta", None)
                    if getattr(delta, "type", None) != "text_delta":
                        continue
                    text = getattr(delta, "text", "")
                    if text:
                        yield ApiTextDeltaEvent(text=text)

                final_message = await stream.get_final_message()
        except APIError as exc:
            if isinstance(exc, APIStatusError) and exc.status_code in RETRYABLE_STATUS_CODES:
                raise  # Let retry logic handle it
            raise _translate_api_error(exc) from exc

        usage = getattr(final_message, "usage", None)
        yield ApiMessageCompleteEvent(
            message=assistant_message_from_api(final_message),
            usage=UsageSnapshot(
                input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            ),
            stop_reason=getattr(final_message, "stop_reason", None),
        )


def _translate_api_error(exc: APIError) -> OpenHarnessApiError:
    """Translate API error for the enclosing subsystem.

    Integration: Called by ``AnthropicApiClient.stream_message``,
    ``AnthropicApiClient._stream_once`` and collaborates with ``RequestFailure``,
    ``AuthenticationFailure``, ``RateLimitFailure``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    name = exc.__class__.__name__
    if name in {"AuthenticationError", "PermissionDeniedError"}:
        return AuthenticationFailure(str(exc))
    if name == "RateLimitError":
        return RateLimitFailure(str(exc))
    return RequestFailure(str(exc))
