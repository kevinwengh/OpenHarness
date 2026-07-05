"""Ohmo-owned workflow effects for channels and personal knowledge."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from openharness.automation.actions import (
    ActionExecutionContext,
    ActionResult,
    AutomationAction,
)
from openharness.channels.bus.events import OutboundMessage
from openharness.channels.bus.queue import MessageBus
from openharness.memory.schema import split_memory_file

from ohmo.automation.events import bounded_event_ancestry
from ohmo.memory import add_memory_entry
from ohmo.workspace import get_attachments_dir

_NAME = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")


class ChannelSendInput(BaseModel):
    """Strict outbound-message fields accepted from rendered workflow data."""

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(min_length=1, max_length=64)
    chat_id: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=100_000)
    thread_id: str | None = Field(default=None, max_length=512)
    reply_to: str | None = Field(default=None, max_length=512)
    media: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("channel")
    @classmethod
    def _normalize_channel(cls, value: str) -> str:
        """Normalize the exact channel adapter identifier."""

        normalized = value.strip().lower()
        if not _NAME.fullmatch(normalized):
            raise ValueError("channel must be a lowercase identifier")
        return normalized

    @field_validator("chat_id", "content", "thread_id", "reply_to")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        """Trim required and optional text fields while rejecting blanks."""

        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class ChannelSendAction(AutomationAction):
    """Publish a policy-authorized message through Ohmo's existing bus.

    Queue acceptance is the only success guarantee; adapters do not expose a
    durable remote-delivery acknowledgement, so this action remains
    intentionally non-retry-safe.
    """

    name = "channel.send"
    description = "Queue a message to a workflow-authorized channel destination."
    input_model = ChannelSendInput

    def __init__(self, bus: MessageBus, workspace: str | Path) -> None:
        """Bind the host bus and resolve the only permitted media root."""

        self._bus = bus
        self._media_root = get_attachments_dir(workspace).expanduser().resolve()

    async def execute(
        self,
        arguments: ChannelSendInput,
        context: ActionExecutionContext,
    ) -> ActionResult:
        """Validate destination/media policy and enqueue one outbound message."""

        allowed = context.run.definition.policy.channel_destinations.get(arguments.channel, [])
        if arguments.chat_id not in allowed:
            return ActionResult(
                is_error=True,
                error_category="channel_destination_denied",
                error_message=(
                    f"destination {arguments.channel}:{arguments.chat_id} is not allowed "
                    "by the workflow"
                ),
            )
        ancestry = bounded_event_ancestry(
            *context.run.event.ancestry,
            context.run.event.id,
            context.run.id,
        )
        metadata: dict[str, object] = {
            "_automation": {
                "generated": True,
                "run_id": context.run.id,
                "workflow_id": context.run.workflow_id,
                "ancestry": ancestry,
            }
        }
        if arguments.thread_id:
            metadata["thread_id"] = arguments.thread_id
            if arguments.channel == "slack":
                metadata["slack"] = {"thread_ts": arguments.thread_id}
        try:
            media = await asyncio.to_thread(
                _resolve_media_paths,
                arguments.media,
                self._media_root,
            )
        except ValueError as exc:
            return ActionResult(
                is_error=True,
                error_category="channel_media_denied",
                error_message=str(exc),
            )
        await self._bus.publish_outbound(
            OutboundMessage(
                channel=arguments.channel,
                chat_id=arguments.chat_id,
                content=arguments.content,
                reply_to=arguments.reply_to,
                media=media,
                metadata=metadata,
            )
        )
        return ActionResult(
            output={
                "queued": True,
                "channel": arguments.channel,
                "chat_id": arguments.chat_id,
            }
        )


class KnowledgeUpsertInput(BaseModel):
    """Strict namespace, title, and content for personal-memory upsert."""

    model_config = ConfigDict(extra="forbid")

    namespace: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=200_000)

    @field_validator("namespace")
    @classmethod
    def _normalize_namespace(cls, value: str) -> str:
        """Normalize the policy and storage namespace identifier."""

        normalized = value.strip().lower()
        if not _NAME.fullmatch(normalized):
            raise ValueError("namespace must be a lowercase identifier")
        return normalized

    @field_validator("title", "content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        """Trim memory title/content and reject empty persisted values."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class KnowledgeUpsertAction(AutomationAction):
    """Upsert one policy-authorized Ohmo personal-memory entry."""

    name = "knowledge.upsert"
    description = "Upsert one workflow-authorized entry in Ohmo personal memory."
    input_model = KnowledgeUpsertInput

    def __init__(self, workspace: str | Path) -> None:
        """Bind the resolved workspace that owns memory schema and index state."""

        self._workspace = Path(workspace).expanduser().resolve()

    def is_retry_safe(self, arguments: KnowledgeUpsertInput) -> bool:
        """Declare replay safe because namespace and title form the stable identity."""

        del arguments
        # Namespace + title is the stable upsert identity; replay updates the same
        # schema-backed file and preserves its memory ID.
        return True

    async def execute(
        self,
        arguments: KnowledgeUpsertInput,
        context: ActionExecutionContext,
    ) -> ActionResult:
        """Enforce namespace policy and write through the memory subsystem."""

        if arguments.namespace not in context.run.definition.policy.knowledge_namespaces:
            return ActionResult(
                is_error=True,
                error_category="knowledge_namespace_denied",
                error_message=(
                    f"knowledge namespace {arguments.namespace!r} is not allowed by the workflow"
                ),
            )
        path = await asyncio.to_thread(
            add_memory_entry,
            self._workspace,
            arguments.title,
            arguments.content,
            namespace=arguments.namespace,
            source=f"automation:{context.run.workflow_id}",
        )
        metadata = await asyncio.to_thread(_read_memory_metadata, path)
        try:
            relative_path = str(path.relative_to(self._workspace))
        except ValueError:
            relative_path = path.name
        return ActionResult(
            output={
                "memory_id": str(metadata.get("id") or path.stem),
                "path": relative_path,
                "namespace": arguments.namespace,
            }
        )


def _read_memory_metadata(path: Path) -> dict:
    """Read only the schema metadata needed for the action result."""

    metadata, _, _, _ = split_memory_file(path.read_text(encoding="utf-8"))
    return metadata


def _resolve_media_paths(references: list[str], root: Path) -> list[str]:
    """Resolve existing files and confine every reference beneath attachments."""

    resolved: list[str] = []
    for reference in references:
        if len(reference) > 4096:
            raise ValueError("channel media path exceeds 4096 characters")
        try:
            path = Path(reference).expanduser().resolve(strict=True)
            path.relative_to(root)
        except (OSError, ValueError) as exc:
            raise ValueError("channel media must be a file in the Ohmo attachments directory") from exc
        if not path.is_file():
            raise ValueError("channel media must be a file in the Ohmo attachments directory")
        resolved.append(str(path))
    return resolved
