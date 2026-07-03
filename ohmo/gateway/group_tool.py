"""ohmo-only Feishu group management tool.

Integration: This ohmo module specializes the reusable OpenHarness runtime with personal
workspace, memory, session, gateway, or channel behavior; core modules must not depend on it.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve the ohmo workspace boundary, conversation/session isolation, attachment
and channel contracts, credential redaction, and cleanup of per-session runtimes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import BaseModel, Field

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

from ohmo.group_registry import normalize_group_name, save_managed_group_record


CreateFeishuGroup = Callable[[str, str], Awaitable[str] | str]
PublishGroupWelcome = Callable[[str, str, str], Awaitable[None] | None]


class OhmoCreateFeishuGroupInput(BaseModel):
    """Arguments selected by the model for creating a Feishu group.

    Integration: Consumed by Pydantic validation and JSON/schema boundaries in the owning
    subsystem.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    name: str = Field(description="Final Feishu group name to create.")
    cwd: str | None = Field(
        default=None,
        description="Workspace directory to bind to the group. Use an absolute path, ~ path, or path relative to cwd.",
    )
    repo: str | None = Field(
        default=None,
        description="Repository identifier associated with the group, for example HKUDS/OpenHarness.",
    )
    reason: str | None = Field(
        default=None,
        description="Short reason explaining why these name/cwd/repo values were chosen.",
    )


class OhmoCreateFeishuGroupTool(BaseTool):
    """Create a Feishu group for the current ohmo private-chat requester.

    Integration: Constructed or referenced by ``OhmoSessionRuntimePool._register_group_tool``.

    Event loop: Async methods ``execute`` run on their caller's loop; instances must retain
    clear task, cancellation, and cleanup ownership.

    Change safety: Keep the input schema, read-only classification, async ``ToolResult``
    contract, permission metadata, hooks, sandbox behavior, and registration synchronized.
    """

    name = "ohmo_create_feishu_group"
    description = (
        "Create a Feishu group for the current private-chat /group request and bind optional cwd/repo metadata. "
        "Only use this after the user explicitly invokes /group. Infer name, cwd, and repo from the user's "
        "natural-language request and the local workspace context; inspect files first if needed."
    )
    input_model = OhmoCreateFeishuGroupInput

    def __init__(
        self,
        *,
        workspace: str | Path | None,
        create_group: CreateFeishuGroup,
        publish_group_welcome: PublishGroupWelcome | None = None,
    ) -> None:
        """Initialize ``OhmoCreateFeishuGroupTool`` and bind its runtime dependencies.

        Integration: Exposed through ``OhmoCreateFeishuGroupTool``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._workspace = workspace
        self._create_group = create_group
        self._publish_group_welcome = publish_group_welcome

    def is_read_only(self, arguments: OhmoCreateFeishuGroupInput) -> bool:
        # Permission is enforced by the slash-command context guard below. This
        # tool is only registered inside ohmo gateway sessions and cannot run
        # unless the current inbound message was a private Feishu /group request.
        """Classify whether this ``OhmoCreateFeishuGroupTool`` invocation can mutate state.

        Integration: Exposed through ``OhmoCreateFeishuGroupTool``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve conservative argument-aware classification used by permission
        policy expected by callers.
        """
        del arguments
        return True

    async def execute(self, arguments: OhmoCreateFeishuGroupInput, context: ToolExecutionContext) -> ToolResult:
        """Execute one model-requested ``OhmoCreateFeishuGroupTool`` invocation.

        Integration: Exposed through ``OhmoCreateFeishuGroupTool`` and collaborates with
        ``_resolve_cwd``, ``ToolResult``, ``normalize_group_name``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the asynchronous ``ToolResult`` contract, ``context.cwd``, and
        normalized operational failures; preserve permission, hook, sandbox, metadata, and
        output-size assumptions; preserve exception and fallback behavior expected by callers.
        """
        request = context.metadata.get("ohmo_group_request")
        if not isinstance(request, dict):
            return ToolResult(
                output="ohmo_create_feishu_group can only run immediately after a Feishu private /group request.",
                is_error=True,
            )
        if request.get("used"):
            return ToolResult(output="This /group request has already created a group.", is_error=True)
        if request.get("channel") != "feishu" or request.get("chat_type") not in {"p2p", "private", "im", "direct", ""}:
            return ToolResult(output="/group group creation is only allowed from a Feishu private chat.", is_error=True)

        owner_open_id = str(request.get("sender_id") or "").strip()
        if not owner_open_id:
            return ToolResult(output="Cannot create group: missing Feishu requester open_id.", is_error=True)

        try:
            name = normalize_group_name(arguments.name)
        except ValueError as exc:
            return ToolResult(output=f"Cannot create group: {exc}", is_error=True)

        cwd = _resolve_cwd(arguments.cwd, context.cwd)
        if cwd is not None and not Path(cwd).is_dir():
            return ToolResult(output=f"Cannot bind cwd because the directory does not exist: {cwd}", is_error=True)

        try:
            result = self._create_group(owner_open_id, name)
            chat_id = await result if asyncio.iscoroutine(result) else result
        except Exception as exc:
            return ToolResult(output=f"Cannot create Feishu group: {exc}", is_error=True)
        chat_id = str(chat_id).strip()
        if not chat_id:
            return ToolResult(output="Cannot create group: Feishu returned an empty chat_id.", is_error=True)

        request["used"] = True
        try:
            record_path = save_managed_group_record(
                workspace=self._workspace,
                channel="feishu",
                chat_id=chat_id,
                owner_open_id=owner_open_id,
                name=name,
                cwd=cwd,
                repo=arguments.repo,
                binding_status="bound" if cwd else "pending_agent",
                metadata={
                    "source": "slash_group_tool",
                    "raw_group_request": request.get("raw_request"),
                    "source_chat_id": request.get("source_chat_id"),
                    "source_session_key": request.get("source_session_key"),
                    "sender_display_name": request.get("sender_display_name"),
                    "tool_reason": arguments.reason,
                },
            )
        except Exception as exc:
            return ToolResult(
                output=f"Created Feishu group {chat_id}, but failed to save metadata: {exc}",
                is_error=True,
                metadata={"chat_id": chat_id},
            )

        welcome = (
            "这个群已经创建好。"
            + (f"\n已绑定工作目录：{cwd}" if cwd else "")
            + (f"\n关联仓库：{arguments.repo}" if arguments.repo else "")
            + "\n这个 ohmo 管理的群默认可以不用 @ 直接和我说话；普通群仍建议 @ohmo 触发。"
            + "\n如果我没有响应，请确认飞书应用已开通接收群聊所有消息的权限。"
        )
        if self._publish_group_welcome is not None:
            published = self._publish_group_welcome(chat_id, welcome, owner_open_id)
            if asyncio.iscoroutine(published):
                await published

        lines = [
            f"Created Feishu group: {name}",
            f"chat_id: {chat_id}",
            f"metadata: {record_path}",
        ]
        if cwd:
            lines.append(f"cwd: {cwd}")
        if arguments.repo:
            lines.append(f"repo: {arguments.repo}")
        return ToolResult(output="\n".join(lines), metadata={"chat_id": chat_id, "cwd": cwd, "repo": arguments.repo})


def _resolve_cwd(raw: str | None, base_cwd: Path) -> str | None:
    """Resolve working directory for the enclosing subsystem.

    Integration: Called by ``OhmoCreateFeishuGroupTool.execute`` and collaborates with
    ``expanduser``, ``path.is_absolute``, ``path.resolve``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if raw is None or not str(raw).strip():
        return None
    path = Path(str(raw).strip()).expanduser()
    if not path.is_absolute():
        path = base_cwd / path
    return str(path.resolve())
