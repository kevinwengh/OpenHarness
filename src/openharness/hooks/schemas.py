"""Hook configuration schemas.

Integration: This module participates in extension callbacks around sessions, prompts,
compaction, tools, notifications, and stopping.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve priority/order, blocking semantics, timeouts, untrusted arguments,
failure policy, and async lifecycle.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CommandHookDefinition(BaseModel):
    """A hook that executes a shell command.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    type: Literal["command"] = "command"
    command: str
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    matcher: str | None = None
    block_on_failure: bool = False
    priority: int = Field(default=0)
    """Higher priority runs first within an event; ties keep registration order."""


class PromptHookDefinition(BaseModel):
    """A hook that asks the model to validate a condition.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    type: Literal["prompt"] = "prompt"
    prompt: str
    model: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    matcher: str | None = None
    block_on_failure: bool = True
    priority: int = Field(default=0)
    """Higher priority runs first within an event; ties keep registration order."""


class HttpHookDefinition(BaseModel):
    """A hook that POSTs the event payload to an HTTP endpoint.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    type: Literal["http"] = "http"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    matcher: str | None = None
    block_on_failure: bool = False
    priority: int = Field(default=0)
    """Higher priority runs first within an event; ties keep registration order."""


class AgentHookDefinition(BaseModel):
    """A hook that performs a deeper model-based validation.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    type: Literal["agent"] = "agent"
    prompt: str
    model: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=1200)
    matcher: str | None = None
    block_on_failure: bool = True
    priority: int = Field(default=0)
    """Higher priority runs first within an event; ties keep registration order."""


HookDefinition = (
    CommandHookDefinition
    | PromptHookDefinition
    | HttpHookDefinition
    | AgentHookDefinition
)
