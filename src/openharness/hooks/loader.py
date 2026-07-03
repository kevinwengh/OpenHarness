"""Load hooks from settings.

Integration: This module participates in extension callbacks around sessions, prompts,
compaction, tools, notifications, and stopping.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve priority/order, blocking semantics, timeouts, untrusted arguments,
failure policy, and async lifecycle.
"""

from __future__ import annotations

from collections import defaultdict
from openharness.hooks.events import HookEvent
from openharness.hooks.schemas import HookDefinition


class HookRegistry:
    """Store hooks grouped by event.

    Integration: Constructed or referenced by ``HookReloader.__init__``,
    ``HookReloader.current_registry``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self) -> None:
        """Initialize ``HookRegistry`` and bind its runtime dependencies.

        Integration: Exposed through ``HookRegistry`` and collaborates with ``defaultdict``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._hooks: dict[HookEvent, list[HookDefinition]] = defaultdict(list)

    def register(self, event: HookEvent, hook: HookDefinition) -> None:
        """Register one hook.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``append``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self._hooks[event].append(hook)

    def get(self, event: HookEvent) -> list[HookDefinition]:
        """Return hooks registered for an event, ordered by priority.

        Hooks with a higher ``priority`` run first. ``sorted`` is stable, so
        hooks sharing the same priority keep their registration order.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        hooks = self._hooks.get(event, [])
        return sorted(hooks, key=lambda hook: -getattr(hook, "priority", 0))

    def summary(self) -> str:
        """Return a human-readable hook summary.

        Integration: Called by ``RuntimeBundle.hook_summary`` and collaborates with ``join``,
        ``get``, ``lines.append``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        lines: list[str] = []
        for event in HookEvent:
            hooks = self.get(event)
            if not hooks:
                continue
            lines.append(f"{event.value}:")
            for hook in hooks:
                matcher = getattr(hook, "matcher", None)
                detail = getattr(hook, "command", None) or getattr(hook, "prompt", None) or getattr(hook, "url", None) or ""
                suffix = f" matcher={matcher}" if matcher else ""
                priority = getattr(hook, "priority", 0)
                if priority:
                    suffix += f" priority={priority}"
                lines.append(f"  - {hook.type}{suffix}: {detail}")
        return "\n".join(lines)


def load_hook_registry(settings, plugins=None) -> HookRegistry:
    """Load hooks from the current settings object.

    Integration: Called by ``HookReloader.current_registry``, ``RuntimeBundle.hook_summary`` and
    collaborates with ``HookRegistry``, ``settings.hooks.items``, ``plugin.hooks.items``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    registry = HookRegistry()
    for raw_event, hooks in settings.hooks.items():
        try:
            event = HookEvent(raw_event)
        except ValueError:
            continue
        for hook in hooks:
            registry.register(event, hook)
    for plugin in plugins or []:
        if not plugin.enabled:
            continue
        for raw_event, hooks in plugin.hooks.items():
            try:
                event = HookEvent(raw_event)
            except ValueError:
                continue
            for hook in hooks:
                registry.register(event, hook)
    return registry
