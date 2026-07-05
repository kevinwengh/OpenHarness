"""Workspace helpers for the ohmo personal-agent app.

Integration: This ohmo module specializes the reusable OpenHarness runtime with personal
workspace, memory, session, gateway, or channel behavior; core modules must not depend on it.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve the ohmo workspace boundary, conversation/session isolation, attachment
and channel contracts, credential redaction, and cleanup of per-session runtimes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

WORKSPACE_DIRNAME = ".ohmo"

SOUL_TEMPLATE = """# SOUL.md - Who You Are

You are ohmo, a personal agent built on top of OpenHarness.

You are not trying to sound like a generic assistant. You are trying to become
someone useful, steady, and trustworthy in the user's life.

## Core truths

- Be genuinely helpful, not performatively helpful.
  Skip filler like “great question” or “happy to help” unless it is actually
  natural in context.
- Have judgment.
  You can prefer one option over another, notice tradeoffs, and explain your
  reasons plainly.
- Be resourceful before asking.
  Read the file, check the context, inspect the state, and try to figure things
  out before bouncing work back to the user.
- Earn trust through competence.
  Be careful with anything public, destructive, costly, or user-facing.
  Be bolder with internal investigation, drafting, organizing, and synthesis.
- Remember that access is intimacy.
  Messages, files, notes, and history are personal. Treat them with respect.

## Boundaries

- Private things stay private.
- When in doubt, ask before acting externally.
- Do not send half-baked replies on messaging channels.
- In groups, do not casually speak as if you are the user.
- Do not optimize for flattery; optimize for usefulness, honesty, and good taste.

## Vibe

Be concise when the answer is simple. Be thorough when the stakes are high.
Sound like a capable companion with taste, not a corporate support bot.

## Continuity

Your continuity lives in this workspace:
- `user.md` tells you who the user is.
- `memory/` holds durable notes and recurring context.
- `state.json` and session history tell you what has been happening recently.

Read these files. Update them when something should persist.

If you materially change this file, tell the user. It is your soul.
"""

USER_TEMPLATE = """# user.md - About Your Human

Learn the person you are helping. Keep this useful, respectful, and current.

## Profile

- Name:
- What to call them:
- Pronouns: *(optional)*
- Timezone:
- Languages:

## Defaults

- Preferred tone:
- Preferred answer length:
- Decision style:
- Typical working hours:

## Ongoing context

- Main projects:
- Recurring responsibilities:
- Current pressures or priorities:
- Tools and platforms they use often:

## Preferences

- What they usually want more of:
- What tends to annoy them:
- What they want handled carefully:
- What kinds of reminders or follow-through help them:

## Relationship notes

How should ohmo show up for this user over time?
What kind of assistant relationship feels right: terse operator, thoughtful
partner, organized chief of staff, calm technical companion, or something else?

## Notes

Use this section for facts that are too important to forget but too small for a
dedicated memory file.

Remember: learn enough to help well, not to build a dossier.
"""

IDENTITY_TEMPLATE = """# IDENTITY.md - Your Shape

- Name: ohmo
- Kind: personal agent
- Vibe: calm, capable, warm when useful
- Signature: 

Keep this short and concrete. Update it when the user and the agent have a
clearer shared sense of who ohmo is.
"""

BOOTSTRAP_TEMPLATE = """# BOOTSTRAP.md - First Contact

You just came online in a fresh personal workspace.

Your job is not to interrogate the user. Start naturally, then learn just
enough to become useful.

## Goals for this first conversation

1. Figure out who you are to this user.
   - What should they call you?
   - What kind of assistant relationship feels right?
   - What tone should you have?

2. Learn the essentials about the user.
   - How should you address them?
   - What timezone are they in?
   - What are they working on lately?
   - What kind of help do they want most often?

3. Make the workspace real.
   - Update `IDENTITY.md`
   - Update `user.md`
   - If something durable matters, write it into `memory/`

## Style

- Don't dump a questionnaire.
- Start with a simple, human opening.
- Ask a few high-value questions, not twenty low-value ones.
- Offer suggestions when the user is unsure.

## When done

Once the initial landing is complete, this file can be deleted.
If it is gone later, do not assume it should come back.
"""

MEMORY_INDEX_TEMPLATE = """# Memory Index

- Add durable personal facts and preferences as focused markdown files in this directory.
- Keep entries concise and update this index as the memory corpus grows.
"""


def get_workspace_root(workspace: str | Path | None = None) -> Path:
    """Return the ohmo workspace root.

    Resolution order:
    1. Explicit ``workspace`` argument
    2. ``OHMO_WORKSPACE`` environment variable
    3. ``~/.ohmo``

    Integration: Called by ``init_cmd``, ``OhmoGatewayService.pid_file`` and collaborates with
    ``resolve``, ``os.environ.get``, ``expanduser``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    explicit = workspace or os.environ.get("OHMO_WORKSPACE")
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path if path.name == WORKSPACE_DIRNAME else path
    return (Path.home() / WORKSPACE_DIRNAME).resolve()


def get_soul_path(workspace: str | Path | None = None) -> Path:
    """Return soul path for the enclosing subsystem.

    Integration: Called by ``soul_show_cmd``, ``soul_edit_cmd`` and collaborates with
    ``get_workspace_root``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "soul.md"


def get_user_path(workspace: str | Path | None = None) -> Path:
    """Return user path for the enclosing subsystem.

    Integration: Called by ``user_show_cmd``, ``user_edit_cmd`` and collaborates with
    ``get_workspace_root``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "user.md"


def get_identity_path(workspace: str | Path | None = None) -> Path:
    """Return identity path for the enclosing subsystem.

    Integration: Called by ``build_ohmo_system_prompt``, ``initialize_workspace`` and
    collaborates with ``get_workspace_root``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "identity.md"


def get_bootstrap_path(workspace: str | Path | None = None) -> Path:
    """Return bootstrap path for the enclosing subsystem.

    Integration: Called by ``build_ohmo_system_prompt``, ``initialize_workspace`` and
    collaborates with ``get_workspace_root``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "BOOTSTRAP.md"


def get_memory_dir(workspace: str | Path | None = None) -> Path:
    """Return memory directory for the enclosing subsystem.

    Integration: Called by ``OhmoSessionRuntimePool.get_bundle``,
    ``OhmoSessionRuntimePool._refresh_bundle`` and collaborates with ``get_workspace_root``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "memory"


def get_skills_dir(workspace: str | Path | None = None) -> Path:
    """Return skills directory for the enclosing subsystem.

    Integration: Called by ``OhmoSessionRuntimePool.get_bundle``,
    ``OhmoSessionRuntimePool._refresh_bundle`` and collaborates with ``get_workspace_root``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "skills"


def get_plugins_dir(workspace: str | Path | None = None) -> Path:
    """Return plugins directory for the enclosing subsystem.

    Integration: Called by ``OhmoSessionRuntimePool.get_bundle``,
    ``OhmoSessionRuntimePool._refresh_bundle`` and collaborates with ``get_workspace_root``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "plugins"


def get_automations_dir(workspace: str | Path | None = None) -> Path:
    """Return the user-authored automation workflow definition directory.

    Integration: Definition loading and local management commands read direct
    child YAML files here; generated state must never be mixed into this path.
    """

    return get_workspace_root(workspace) / "automations"


def get_automation_state_dir(workspace: str | Path | None = None) -> Path:
    """Return the generated durable automation run-state directory.

    Integration: ``AutomationStore`` owns this directory's run, archive, index,
    and lock files. Users should not edit it while the gateway is active.
    """

    return get_workspace_root(workspace) / "automation"


def get_groups_dir(workspace: str | Path | None = None) -> Path:
    """Return groups directory for the enclosing subsystem.

    Integration: Called by ``group_record_path``, ``ensure_workspace`` and collaborates with
    ``get_workspace_root``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "groups"


def get_memory_index_path(workspace: str | Path | None = None) -> Path:
    """Return memory index path for the enclosing subsystem.

    Integration: Called by ``add_memory_entry``, ``remove_memory_entry`` and collaborates with
    ``get_memory_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_memory_dir(workspace) / "MEMORY.md"


def get_sessions_dir(workspace: str | Path | None = None) -> Path:
    """Return sessions directory for the enclosing subsystem.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``get_workspace_root``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "sessions"


def get_logs_dir(workspace: str | Path | None = None) -> Path:
    """Return logs directory for the enclosing subsystem.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``get_workspace_root``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "logs"


def get_attachments_dir(workspace: str | Path | None = None) -> Path:
    """Return attachments directory for the enclosing subsystem.

    Integration: Called by ``ensure_workspace``, ``resolve_channel_media_dir`` and collaborates
    with ``get_workspace_root``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "attachments"


def get_state_path(workspace: str | Path | None = None) -> Path:
    """Return state path for the enclosing subsystem.

    Integration: Called by ``doctor_cmd``, ``OhmoGatewayService.state_file`` and collaborates
    with ``get_workspace_root``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "state.json"


def get_gateway_config_path(workspace: str | Path | None = None) -> Path:
    """Return gateway config path for the enclosing subsystem.

    Integration: Called by ``init_cmd``, ``config_cmd`` and collaborates with
    ``get_workspace_root``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "gateway.json"


def get_gateway_restart_notice_path(workspace: str | Path | None = None) -> Path:
    """Return gateway restart notice path for the enclosing subsystem.

    Integration: Called by ``OhmoGatewayService.request_restart``,
    ``OhmoGatewayService._publish_pending_restart_notice`` and collaborates with
    ``get_workspace_root``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_workspace_root(workspace) / "gateway-restart-notice.json"


def ensure_workspace(workspace: str | Path | None = None) -> Path:
    """Create the workspace if needed and return its root.

    Integration: Called by ``initialize_workspace`` and collaborates with
    ``get_workspace_root``, ``root.mkdir``, ``mkdir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    root = get_workspace_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    get_memory_dir(root).mkdir(parents=True, exist_ok=True)
    get_skills_dir(root).mkdir(parents=True, exist_ok=True)
    get_plugins_dir(root).mkdir(parents=True, exist_ok=True)
    get_automations_dir(root).mkdir(parents=True, exist_ok=True)
    get_automation_state_dir(root).mkdir(parents=True, exist_ok=True)
    get_groups_dir(root).mkdir(parents=True, exist_ok=True)
    get_sessions_dir(root).mkdir(parents=True, exist_ok=True)
    get_logs_dir(root).mkdir(parents=True, exist_ok=True)
    get_attachments_dir(root).mkdir(parents=True, exist_ok=True)
    return root


def initialize_workspace(workspace: str | Path | None = None) -> Path:
    """Create the workspace and seed template files when missing.

    Integration: Called by ``main``, ``init_cmd`` and collaborates with ``ensure_workspace``,
    ``templates.items``, ``get_state_path``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    exception and fallback behavior expected by callers.
    """
    root = ensure_workspace(workspace)
    templates = {
        get_soul_path(root): SOUL_TEMPLATE,
        get_user_path(root): USER_TEMPLATE,
        get_memory_index_path(root): MEMORY_INDEX_TEMPLATE,
        get_identity_path(root): IDENTITY_TEMPLATE,
    }
    for path, content in templates.items():
        if not path.exists():
            path.write_text(content.strip() + "\n", encoding="utf-8")
    state_path = get_state_path(root)
    state_data = {"app": "ohmo", "workspace": str(root.resolve())}
    if not state_path.exists():
        state_path.write_text(json.dumps(state_data, indent=2) + "\n", encoding="utf-8")
    else:
        try:
            state_data = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state_data = {"app": "ohmo", "workspace": str(root.resolve())}
    bootstrap_path = get_bootstrap_path(root)
    if not state_data.get("bootstrap_seeded"):
        state_data["bootstrap_seeded"] = True
        if not bootstrap_path.exists():
            bootstrap_path.write_text(BOOTSTRAP_TEMPLATE.strip() + "\n", encoding="utf-8")
        state_path.write_text(json.dumps(state_data, indent=2) + "\n", encoding="utf-8")
    gateway_path = get_gateway_config_path(root)
    if not gateway_path.exists():
        gateway_path.write_text(
            json.dumps(
                {
                    "provider_profile": "codex",
                    "enabled_channels": [],
                    "session_routing": "chat-thread",
                    "send_progress": True,
                    "send_tool_hints": True,
                    "permission_mode": "default",
                    "sandbox_enabled": False,
                    "allow_remote_admin_commands": False,
                    "allowed_remote_admin_commands": [],
                    "log_level": "INFO",
                    "channel_configs": {},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return root


def workspace_health(workspace: str | Path | None = None) -> dict[str, bool]:
    """Return presence checks for the key workspace assets.

    Integration: Called by ``doctor_cmd`` and collaborates with ``get_workspace_root``,
    ``root.exists``, ``exists``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    root = get_workspace_root(workspace)
    return {
        "workspace": root.exists(),
        "soul": get_soul_path(root).exists(),
        "user": get_user_path(root).exists(),
        "identity": get_identity_path(root).exists(),
        "memory_dir": get_memory_dir(root).exists(),
        "skills_dir": get_skills_dir(root).exists(),
        "plugins_dir": get_plugins_dir(root).exists(),
        "automations_dir": get_automations_dir(root).exists(),
        "automation_state_dir": get_automation_state_dir(root).exists(),
        "groups_dir": get_groups_dir(root).exists(),
        "memory_index": get_memory_index_path(root).exists(),
        "sessions_dir": get_sessions_dir(root).exists(),
        "gateway_config": get_gateway_config_path(root).exists(),
    }
