"""Convert images to text descriptions using a multimodal model.

This tool acts as a bridge for pure-text models: when the user attaches an
image but the active model cannot process images natively, the agent loop
(or the model itself) can invoke this tool to obtain a text/JSON description
of the image via a separately configured vision-capable model.

Integration: This module participates in model-callable tools registered with the shared engine
governance path.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve Pydantic schemas, async ToolResult behavior, read-only policy,
context.cwd, hooks, sandboxing, output bounds, and registration.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from openharness.api.openai_client import OpenAICompatibleClient
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

log = logging.getLogger(__name__)

# Default system prompt for image description.
_DEFAULT_VISION_PROMPT = (
    "You are an image description assistant. "
    "Describe the image in detail, including any text, objects, people, "
    "colors, layout, and context. If the image contains code, UI screenshots, "
    "diagrams, or data visualizations, describe them precisely so that a "
    "text-only AI model can understand the content."
)


class ImageToTextToolInput(BaseModel):
    """Arguments for converting an image to text.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    image_data: str | None = Field(
        default=None,
        description="Base64-encoded image data. Provide either image_data or image_path.",
    )
    image_path: str | None = Field(
        default=None,
        description="Local file path to the image. Provide either image_data or image_path.",
    )
    prompt: str = Field(
        default=_DEFAULT_VISION_PROMPT,
        description="Custom instruction for describing the image. "
        "Defaults to a general-purpose description prompt.",
    )
    media_type: str = Field(
        default="image/png",
        description="MIME type of the image (e.g. image/png, image/jpeg, image/webp). "
        "Only used when image_data is provided.",
    )
    max_tokens: int = Field(
        default=2048,
        ge=256,
        le=16384,
        description="Maximum tokens for the vision model response.",
    )


class ImageToTextTool(BaseTool):
    """Use a multimodal model to describe an image and return text.

    Integration: Constructed or referenced by ``create_default_tool_registry``.

    Event loop: Async methods ``execute``, ``_resolve_image``, ``_call_vision_model`` run on
    their caller's loop; instances must retain clear task, cancellation, and cleanup ownership.

    Change safety: Keep the input schema, read-only classification, async ``ToolResult``
    contract, permission metadata, hooks, sandbox behavior, and registration synchronized.
    """

    name = "image_to_text"
    description = (
        "Convert an image to a detailed text description using a vision-capable model. "
        "Use this when you need to understand the content of an image but your current "
        "model does not support image input."
    )
    input_model = ImageToTextToolInput

    async def execute(
        self, arguments: ImageToTextToolInput, context: ToolExecutionContext
    ) -> ToolResult:
        # 1. Resolve image data
        """Execute one model-requested ``ImageToTextTool`` invocation.

        Integration: Exposed through ``ImageToTextTool`` and collaborates with ``ToolResult``,
        ``_resolve_image``, ``log.warning``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the asynchronous ``ToolResult`` contract, ``context.cwd``, and
        normalized operational failures; preserve permission, hook, sandbox, metadata, and
        output-size assumptions; preserve exception and fallback behavior expected by callers.

        Tool contract: The engine validates the Pydantic input and applies hooks and permission
        policy before awaiting this method. Return ``ToolResult`` for expected operational
        failures, resolve paths from ``context.cwd``, keep output and metadata serializable and
        bounded, and do not block the event loop. Revisit sandbox routing, secret redaction,
        tool-result replay, and registration whenever execution behavior changes.
        """
        image_data, media_type = await self._resolve_image(arguments, context)
        if image_data is None:
            return ToolResult(
                output="image_to_text failed: provide either image_data (base64) or image_path",
                is_error=True,
            )

        # 2. Get vision model config from context metadata
        vision_config = context.metadata.get("vision_model_config", {})
        if not isinstance(vision_config, dict):
            vision_config = {}

        model = vision_config.get("model", "")
        api_key = vision_config.get("api_key", "")
        base_url = vision_config.get("base_url", "")

        if not model or not api_key:
            log.warning(
                "image_to_text: vision model not configured. "
                "Set vision.model and vision.api_key in settings."
            )
            return ToolResult(
                output=(
                    "image_to_text failed: vision model is not configured. "
                    "Please set vision.model and vision.api_key in your settings, "
                    "or configure the OPENHARNESS_VISION_MODEL and "
                    "OPENHARNESS_VISION_API_KEY environment variables."
                ),
                is_error=True,
            )

        # 3. Call the vision model
        try:
            description = await self._call_vision_model(
                image_data=image_data,
                media_type=media_type or arguments.media_type,
                prompt=arguments.prompt,
                model=model,
                api_key=api_key,
                base_url=base_url,
                max_tokens=arguments.max_tokens,
            )
        except Exception as exc:
            log.exception("image_to_text: vision model call failed")
            return ToolResult(
                output=f"image_to_text failed: vision model error: {exc}",
                is_error=True,
            )

        return ToolResult(
            output=(
                f"[Image description via {model}]\n\n{description}"
            )
        )

    def is_read_only(self, arguments: BaseModel) -> bool:
        """Classify whether this ``ImageToTextTool`` invocation can mutate state.

        Integration: Exposed through ``ImageToTextTool``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve conservative argument-aware classification used by permission
        policy expected by callers.

        Tool contract: Permission policy trusts this argument-aware classification before
        execution. Return ``True`` only when the invocation cannot mutate local files,
        processes, remote services, configuration, or shared runtime state; prefer a
        conservative ``False`` when uncertain.
        """
        del arguments
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _resolve_image(
        arguments: ImageToTextToolInput,
        context: ToolExecutionContext,
    ) -> tuple[str | None, str | None]:
        """Resolve image data from either base64 string or file path.

        Integration: Called by ``ImageToTextTool.execute`` and collaborates with ``Path``,
        ``resolve``, ``path.suffix.lower``.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        if arguments.image_data:
            return arguments.image_data, arguments.media_type

        if arguments.image_path:
            path = Path(arguments.image_path)
            if not path.is_absolute():
                path = context.cwd / path
            path = path.expanduser().resolve()

            if not path.exists():
                log.warning("image_to_text: image not found at %s", path)
                return None, None

            try:
                raw = path.read_bytes()
                data = base64.b64encode(raw).decode("ascii")
            except OSError as exc:
                log.warning("image_to_text: failed to read %s: %s", path, exc)
                return None, None

            # Guess media type from extension
            ext = path.suffix.lower()
            media_type = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".bmp": "image/bmp",
                ".svg": "image/svg+xml",
            }.get(ext, "image/png")

            return data, media_type

        return None, None

    @staticmethod
    async def _call_vision_model(
        *,
        image_data: str,
        media_type: str,
        prompt: str,
        model: str,
        api_key: str,
        base_url: str,
        max_tokens: int,
    ) -> str:
        """Call the vision model via OpenAI-compatible API.

        Integration: Called by ``ImageToTextTool.execute`` and collaborates with
        ``OpenAICompatibleClient``, ``user_content.append``, ``ConversationMessage``.

        Event loop: This coroutine executes synchronously until it returns; filesystem or
        process work therefore runs inline on the caller's loop. Keep that work bounded or
        offload it before it can block; retain lock scope and release behavior.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        client = OpenAICompatibleClient(
            api_key=api_key,
            base_url=base_url or None,
        )

        from openharness.api.client import ApiMessageRequest
        from openharness.engine.messages import (
            ConversationMessage,
            ImageBlock,
            TextBlock,
        )

        # Build a user message with the image
        user_content: list[Any] = [TextBlock(text=prompt)]
        user_content.append(
            ImageBlock(
                media_type=media_type,
                data=image_data,
            )
        )
        user_message = ConversationMessage(role="user", content=user_content)

        # Stream the response and collect text
        collected_text = ""
        async for event in client.stream_message(
            ApiMessageRequest(
                model=model,
                messages=[user_message],
                system_prompt="",
                max_tokens=max_tokens,
                tools=[],
            )
        ):
            from openharness.api.client import ApiTextDeltaEvent, ApiMessageCompleteEvent

            if isinstance(event, ApiTextDeltaEvent):
                collected_text += event.text
            elif isinstance(event, ApiMessageCompleteEvent):
                # Also grab any text from the final message
                text = event.message.text
                if text and text not in collected_text:
                    collected_text = text

        return collected_text.strip() or "(no description returned)"
