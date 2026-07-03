"""GitHub Copilot API client for OpenHarness.

Wraps :class:`OpenAICompatibleClient` with Copilot-specific headers.
The Copilot chat endpoint is OpenAI-compatible, so all message/tool
conversion is delegated to the inner client.

Authentication uses the persisted GitHub OAuth token directly
(``Authorization: Bearer <token>``) — no additional token exchange
is required.

Integration: This module participates in provider streaming clients and normalized request/event
contracts.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve request conversion, streamed tool calls, usage/errors, auth secrecy,
retries, and multi-turn replay.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from openharness.api.client import (
    ApiMessageRequest,
    ApiStreamEvent,
)
from openharness.api.copilot_auth import (
    copilot_api_base,
    load_copilot_auth,
)
from openharness.api.errors import AuthenticationFailure
from openharness.api.openai_client import OpenAICompatibleClient

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Header constants
# ---------------------------------------------------------------------------

_VERSION = "0.1.0"  # OpenHarness version for User-Agent

# Default model for Copilot requests when the configured model is not
# available in the Copilot model catalog.
COPILOT_DEFAULT_MODEL = "gpt-4o"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class CopilotClient:
    """Copilot-aware API client implementing ``SupportsStreamingMessages``.

    Uses the GitHub OAuth token directly as a Bearer token for the
    Copilot API.  No token exchange or session management is needed.

    Parameters
    ----------
    github_token:
        GitHub OAuth token (``ghu_...`` / ``gho_...``).  If *None*, the
        token is loaded from ``~/.openharness/copilot_auth.json``.
    enterprise_url:
        Optional enterprise domain.  If *None*, loaded from the
        persisted auth file (falls back to public GitHub).
    model:
        Default model to request.  Can be overridden per-request via
        ``ApiMessageRequest.model``.

    Integration: Constructed or referenced by ``_resolve_api_client_from_settings``.

    Event loop: Async methods ``stream_message``, ``close`` run on their caller's loop;
    instances must retain clear task, cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(
        self,
        github_token: str | None = None,
        *,
        enterprise_url: str | None = None,
        model: str | None = None,
    ) -> None:
        """Initialize ``CopilotClient`` and bind its runtime dependencies.

        Integration: Exposed through ``CopilotClient`` and collaborates with
        ``load_copilot_auth``, ``copilot_api_base``, ``AsyncOpenAI``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        auth_info = load_copilot_auth()
        token = github_token or (auth_info.github_token if auth_info else None)
        if not token:
            raise AuthenticationFailure(
                "No GitHub Copilot token found. Run 'oh auth copilot-login' first."
            )

        # Resolve enterprise_url: explicit arg > persisted auth > None (public)
        ent_url = enterprise_url or (auth_info.enterprise_url if auth_info else None)

        self._token = token
        self._enterprise_url = ent_url
        self._model = model

        # Build the inner OpenAI-compatible client once.
        base_url = copilot_api_base(ent_url)
        default_headers: dict[str, str] = {
            "User-Agent": f"openharness/{_VERSION}",
            "Openai-Intent": "conversation-edits",
        }
        raw_openai = AsyncOpenAI(
            api_key=token,
            base_url=base_url,
            default_headers=default_headers,
        )
        self._inner = OpenAICompatibleClient(
            api_key=token,
            base_url=base_url,
        )
        # Swap the underlying SDK client so Copilot headers are used.
        self._inner._client = raw_openai  # noqa: SLF001

        log.info(
            "CopilotClient initialised (api_base=%s, enterprise=%s)",
            base_url,
            ent_url or "none",
        )

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """Stream one provider response as normalized API events.

        Satisfies the ``SupportsStreamingMessages`` protocol expected by
        the OpenHarness query engine.

        If a *model* was provided at construction time it overrides the
        model in *request*; otherwise the request model is passed through.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``ApiMessageRequest``.

        Event loop: This async generator preserves streamed ordering and caller-driven
        cancellation.

        Change safety: Preserve yield ordering and partial-consumption behavior expected by
        callers.

        Provider contract: Preserve request translation for system prompts, messages, images,
        tool schemas, reasoning effort, and output limits; preserve streamed text/reasoning and
        incremental tool-call identifiers and arguments; emit one normalized final message with
        usage; translate auth, timeout, rate-limit, malformed-stream, and retry failures without
        exposing credentials. Any change must also verify multi-turn assistant tool-call replay
        followed by matching tool results.
        """
        effective_model = self._model or request.model
        patched = ApiMessageRequest(
            model=effective_model,
            messages=request.messages,
            system_prompt=request.system_prompt,
            max_tokens=request.max_tokens,
            tools=request.tools,
        )
        async for event in self._inner.stream_message(patched):
            yield event

    async def close(self) -> None:
        """Close the underlying OpenAI-compatible client.

        Integration: Exposed as a public entrypoint for this subsystem.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        await self._inner.close()
