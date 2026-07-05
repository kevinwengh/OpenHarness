from __future__ import annotations

import pytest

from openharness.api.client import ApiMessageCompleteEvent
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage, TextBlock
from openharness.ui.runtime import build_runtime, close_runtime, start_runtime


class StaticClient:
    async def stream_message(self, request):
        del request
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(role="assistant", content=[TextBlock(text="ok")]),
            usage=UsageSnapshot(),
            stop_reason=None,
        )


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))


@pytest.mark.asyncio
async def test_build_runtime_filters_tools_to_explicit_allowlist(tmp_path) -> None:
    bundle = await build_runtime(
        cwd=str(tmp_path),
        api_client=StaticClient(),
        tool_allowlist=["read_file", "glob", "read_file"],
    )
    try:
        assert [tool.name for tool in bundle.tool_registry.list_tools()] == ["read_file", "glob"]
        assert bundle.tool_allowlist == ("read_file", "glob")
        assert bundle.post_turn_memory_enabled is True
        assert bundle.session_lifecycle_enabled is True
    finally:
        await close_runtime(bundle)


@pytest.mark.asyncio
async def test_build_runtime_can_disable_post_turn_memory(tmp_path) -> None:
    bundle = await build_runtime(
        cwd=str(tmp_path),
        api_client=StaticClient(),
        post_turn_memory_enabled=False,
        session_lifecycle_enabled=False,
    )
    try:
        assert bundle.post_turn_memory_enabled is False
        assert bundle.engine._post_turn_memory_enabled is False
        assert bundle.session_lifecycle_enabled is False
    finally:
        await close_runtime(bundle)


@pytest.mark.asyncio
async def test_disabled_session_lifecycle_skips_hooks_and_personalization(
    tmp_path,
    monkeypatch,
) -> None:
    bundle = await build_runtime(
        cwd=str(tmp_path),
        api_client=StaticClient(),
        session_lifecycle_enabled=False,
    )
    hook_events = []
    personalization_calls = []

    async def record_hook(event, context):
        hook_events.append((event, context))
        return []

    monkeypatch.setattr(bundle.hook_executor, "execute", record_hook)
    monkeypatch.setattr(
        "openharness.personalization.session_hook.update_rules_from_session",
        lambda messages: personalization_calls.append(messages),
    )

    await start_runtime(bundle)
    await close_runtime(bundle)

    assert hook_events == []
    assert personalization_calls == []


@pytest.mark.asyncio
async def test_build_runtime_rejects_missing_allowed_tool(tmp_path) -> None:
    with pytest.raises(ValueError, match="unavailable tools: missing_tool"):
        await build_runtime(
            cwd=str(tmp_path),
            api_client=StaticClient(),
            tool_allowlist=["missing_tool"],
        )
