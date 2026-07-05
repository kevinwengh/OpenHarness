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

from ohmo.memory import add_memory_entry
from ohmo.workspace import get_attachments_dir

_NAME = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")


class ChannelSendInput(BaseModel):
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
        normalized = value.strip().lower()
        if not _NAME.fullmatch(normalized):
            raise ValueError("channel must be a lowercase identifier")
        return normalized

    @field_validator("chat_id", "content", "thread_id", "reply_to")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class ChannelSendAction(AutomationAction):
    name = "channel.send"
    description = "Queue a message to a workflow-authorized channel destination."
    input_model = ChannelSendInput

    def __init__(self, bus: MessageBus, workspace: str | Path) -> None:
        self._bus = bus
        self._media_root = get_attachments_dir(workspace).expanduser().resolve()

    async def execute(
        self,
        arguments: ChannelSendInput,
        context: ActionExecutionContext,
    ) -> ActionResult:
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
        ancestry = [
            *context.run.event.ancestry,
            context.run.event.id,
            context.run.id,
        ][-16:]
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
    model_config = ConfigDict(extra="forbid")

    namespace: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=200_000)

    @field_validator("namespace")
    @classmethod
    def _normalize_namespace(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _NAME.fullmatch(normalized):
            raise ValueError("namespace must be a lowercase identifier")
        return normalized

    @field_validator("title", "content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class KnowledgeUpsertAction(AutomationAction):
    name = "knowledge.upsert"
    description = "Upsert one workflow-authorized entry in Ohmo personal memory."
    input_model = KnowledgeUpsertInput

    def __init__(self, workspace: str | Path) -> None:
        self._workspace = Path(workspace).expanduser().resolve()

    def is_retry_safe(self, arguments: KnowledgeUpsertInput) -> bool:
        del arguments
        # Namespace + title is the stable upsert identity; replay updates the same
        # schema-backed file and preserves its memory ID.
        return True

    async def execute(
        self,
        arguments: KnowledgeUpsertInput,
        context: ActionExecutionContext,
    ) -> ActionResult:
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
    metadata, _, _, _ = split_memory_file(path.read_text(encoding="utf-8"))
    return metadata


def _resolve_media_paths(references: list[str], root: Path) -> list[str]:
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
