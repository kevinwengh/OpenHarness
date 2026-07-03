"""Hook event names supported by OpenHarness.

Integration: This module participates in extension callbacks around sessions, prompts,
compaction, tools, notifications, and stopping.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve priority/order, blocking semantics, timeouts, untrusted arguments,
failure policy, and async lifecycle.
"""

from __future__ import annotations

from enum import Enum


class HookEvent(str, Enum):
    """Events that can trigger hooks.

    Integration: Constructed or referenced by ``load_hook_registry``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve persisted and wire-visible values or provide an explicit migration
    for stored configuration and messages.
    """

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    PRE_COMPACT = "pre_compact"
    POST_COMPACT = "post_compact"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    NOTIFICATION = "notification"
    STOP = "stop"
    SUBAGENT_STOP = "subagent_stop"
