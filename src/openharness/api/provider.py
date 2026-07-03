"""Provider/auth capability helpers.

Integration: This module participates in provider streaming clients and normalized request/event
contracts.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve request conversion, streamed tool calls, usage/errors, auth secrecy,
retries, and multi-turn replay.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from openharness.auth.external import describe_external_binding
from openharness.auth.storage import load_external_binding
from openharness.api.registry import detect_provider_from_registry
from openharness.config.settings import Settings

_AUTH_KIND: dict[str, str] = {
    "anthropic": "api_key",
    "openai_compat": "api_key",
    "copilot": "oauth_device",
    "openai_codex": "external_oauth",
    "anthropic_claude": "external_oauth",
}

_VOICE_REASON: dict[str, str] = {
    "anthropic": (
        "voice mode shell exists, but live voice auth/streaming is not configured in this build"
    ),
    "openai_compat": "voice mode is not wired for OpenAI-compatible providers in this build",
    "copilot": "voice mode is not supported for GitHub Copilot",
    "openai_codex": "voice mode is not supported for Codex subscription auth",
    "anthropic_claude": "voice mode is not supported for Claude subscription auth",
}


@dataclass(frozen=True)
class ProviderInfo:
    """Resolved provider metadata for UI and diagnostics.

    Integration: Constructed or referenced by ``detect_provider``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    name: str
    auth_kind: str
    voice_supported: bool
    voice_reason: str


def detect_provider(settings: Settings) -> ProviderInfo:
    """Infer the active provider and rough capability set using the registry.

    Integration: Called by ``_build_dry_run_preview``, ``create_default_command_registry`` and
    collaborates with ``detect_provider_from_registry``, ``ProviderInfo``, ``_AUTH_KIND.get``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if settings.provider == "openai_codex":
        return ProviderInfo(
            name="openai-codex",
            auth_kind="external_oauth",
            voice_supported=False,
            voice_reason=_VOICE_REASON["openai_codex"],
        )
    if settings.provider == "anthropic_claude":
        return ProviderInfo(
            name="claude-subscription",
            auth_kind="external_oauth",
            voice_supported=False,
            voice_reason=_VOICE_REASON["anthropic_claude"],
        )
    if settings.api_format == "copilot":
        return ProviderInfo(
            name="github_copilot",
            auth_kind="oauth_device",
            voice_supported=False,
            voice_reason=_VOICE_REASON["copilot"],
        )

    spec = detect_provider_from_registry(
        model=settings.model,
        api_key=settings.api_key or None,
        base_url=settings.base_url,
    )

    if spec is not None:
        backend = spec.backend_type
        return ProviderInfo(
            name=spec.name,
            auth_kind=_AUTH_KIND.get(backend, "api_key"),
            voice_supported=False,
            voice_reason=_VOICE_REASON.get(backend, "voice mode is not supported for this provider"),
        )

    # Fallback: use api_format to pick a sensible default
    if settings.api_format == "openai":
        return ProviderInfo(
            name="openai-compatible",
            auth_kind="api_key",
            voice_supported=False,
            voice_reason=_VOICE_REASON["openai_compat"],
        )
    return ProviderInfo(
        name="anthropic",
        auth_kind="api_key",
        voice_supported=False,
        voice_reason=_VOICE_REASON["anthropic"],
    )


def auth_status(settings: Settings) -> str:
    """Return a compact auth status string.

    Integration: Called by ``_build_dry_run_preview``, ``create_default_command_registry`` and
    collaborates with ``resolved.source.startswith``, ``load_copilot_auth``,
    ``settings.resolve_auth``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if settings.api_format == "copilot":
        from openharness.api.copilot_auth import load_copilot_auth

        auth_info = load_copilot_auth()
        if not auth_info:
            return "missing (run 'oh auth copilot-login')"
        if auth_info.enterprise_url:
            return f"configured (enterprise: {auth_info.enterprise_url})"
        return "configured"
    try:
        resolved = settings.resolve_auth()
    except ValueError as exc:
        if settings.provider == "openai_codex":
            return "missing (run 'oh auth codex-login')"
        if settings.provider == "anthropic_claude":
            binding = load_external_binding("anthropic_claude")
            if binding is not None:
                external_state = describe_external_binding(binding)
                if external_state.state != "missing":
                    return external_state.state
            message = str(exc)
            if "third-party" in message:
                return "invalid base_url"
            return "missing (run 'oh auth claude-login')"
        return "missing"
    if resolved.source.startswith("external:"):
        return f"configured ({resolved.source.removeprefix('external:')})"
    return "configured"


# ---------------------------------------------------------------------------
# Multimodal (vision) capability detection
# ---------------------------------------------------------------------------

# Known multimodal model patterns (lowercase, regex).
# These models can accept image input natively.
_MULTIMODAL_MODEL_PATTERNS: list[re.Pattern[str]] = [
    # Anthropic Claude 3+ (all Claude 3 and later support images)
    re.compile(r"^claude-3(?:\.\d+)?(?:-sonnet|-opus|-haiku)?"),
    re.compile(r"^claude-(?:sonnet|opus|haiku)-\d"),
    # OpenAI GPT-4o / o-series
    re.compile(r"^gpt-4o"),
    re.compile(r"^o[1349]-"),
    # Google Gemini
    re.compile(r"^gemini-(?:pro-)?vision"),
    re.compile(r"^gemini-2\.\d+"),
    # Qwen / DashScope VL series
    re.compile(r"^qwen-vl"),
    re.compile(r"^qwen2\.5?-vl"),
    re.compile(r"^qvq-"),
    # DeepSeek VL
    re.compile(r"^deepseek-vl"),
    re.compile(r"^deepseek-vision"),
    # Open-source multimodal
    re.compile(r"^llava"),
    re.compile(r"^cogvlm"),
    re.compile(r"^internvl"),
    re.compile(r"^glm-4v"),
    # Moonshot / Kimi (k2.5 supports images)
    re.compile(r"^kimi-k2\.5"),
    # StepFun (阶跃星辰) — Step-2 and Step-1v support images
    re.compile(r"^step-2"),
    re.compile(r"^step-1v"),
    # MiniMax VL
    re.compile(r"^minimax-vl"),
    # Zhipu GLM-4V
    re.compile(r"^glm-4v"),
    # Mistral Pixtral
    re.compile(r"^pixtral"),
    # Groq vision models (llama-3.2-vision, etc.)
    re.compile(r"vision"),
    # Generic: model names containing "vl" or "vision" as a word boundary
    re.compile(r"(?:^|[-\s/])vl(?:$|[-\s])"),
]


def is_model_multimodal(model: str) -> bool:
    """Return True when the model name indicates multimodal (vision) capability.

    This is a heuristic based on known model naming conventions.  It errs on
    the side of returning False for unknown models so that the image-to-text
    fallback tool is used rather than silently failing.

    Integration: Called by ``_preprocess_images_in_messages`` and collaborates with ``lower``,
    ``any``, ``model.strip``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    normalized = model.strip().lower()
    # Strip provider prefix like "anthropic/" or "openai/"
    if "/" in normalized:
        normalized = normalized.split("/", 1)[-1]
    return any(pattern.search(normalized) is not None for pattern in _MULTIMODAL_MODEL_PATTERNS)
