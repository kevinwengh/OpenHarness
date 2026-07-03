"""Path resolution for OpenHarness configuration and data directories.

Follows XDG-like conventions with ~/.openharness/ as the default base directory.

Integration: This module participates in settings models, persisted profiles, environment input,
and CLI override precedence.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve backward-compatible fields/defaults, secret redaction, profile
materialization, and atomic persistence.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_BASE_DIR = ".openharness"
_CONFIG_FILE_NAME = "settings.json"


def get_config_dir() -> Path:
    """Return the configuration directory, creating it if needed.

    Resolution order:
    1. OPENHARNESS_CONFIG_DIR environment variable
    2. ~/.openharness/

    Integration: Called by ``test_install_real_skills``, ``_auth_file_path`` and collaborates
    with ``os.environ.get``, ``config_dir.mkdir``, ``Path``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    env_dir = os.environ.get("OPENHARNESS_CONFIG_DIR")
    if env_dir:
        config_dir = Path(env_dir)
    else:
        config_dir = Path.home() / _DEFAULT_BASE_DIR

    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_file_path() -> Path:
    """Return the path to the main settings file (~/.openharness/settings.json).

    Integration: Called by ``_build_dry_run_preview``, ``load_settings`` and collaborates with
    ``get_config_dir``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_config_dir() / _CONFIG_FILE_NAME


def get_data_dir() -> Path:
    """Return the data directory for caches, history, etc.

    Resolution order:
    1. OPENHARNESS_DATA_DIR environment variable
    2. ~/.openharness/data/

    Integration: Called by ``BridgeSessionManager.spawn``, ``resolve_channel_media_dir`` and
    collaborates with ``os.environ.get``, ``data_dir.mkdir``, ``Path``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    env_dir = os.environ.get("OPENHARNESS_DATA_DIR")
    if env_dir:
        data_dir = Path(env_dir)
    else:
        data_dir = get_config_dir() / "data"

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_logs_dir() -> Path:
    """Return the logs directory.

    Resolution order:
    1. OPENHARNESS_LOGS_DIR environment variable
    2. ~/.openharness/logs/

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``os.environ.get``, ``logs_dir.mkdir``, ``Path``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    env_dir = os.environ.get("OPENHARNESS_LOGS_DIR")
    if env_dir:
        logs_dir = Path(env_dir)
    else:
        logs_dir = get_config_dir() / "logs"

    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def get_sessions_dir() -> Path:
    """Return the session storage directory.

    Integration: Exposed as a public entrypoint for this subsystem and collaborates with
    ``sessions_dir.mkdir``, ``get_data_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    sessions_dir = get_data_dir() / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def get_tasks_dir() -> Path:
    """Return the background task output directory.

    Integration: Called by ``BackgroundTaskManager.create_shell_task``, ``get_task_manager`` and
    collaborates with ``tasks_dir.mkdir``, ``get_data_dir``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    tasks_dir = get_data_dir() / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    return tasks_dir


def get_feedback_dir() -> Path:
    """Return the feedback storage directory.

    Integration: Called by ``get_feedback_log_path`` and collaborates with
    ``feedback_dir.mkdir``, ``get_data_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    feedback_dir = get_data_dir() / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    return feedback_dir


def get_feedback_log_path() -> Path:
    """Return the feedback log file path.

    Integration: Called by ``create_default_command_registry``,
    ``create_default_command_registry._feedback_handler`` and collaborates with
    ``get_feedback_dir``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_feedback_dir() / "feedback.log"


def get_cron_registry_path() -> Path:
    """Return the cron registry file path.

    Integration: Called by ``_cron_lock_path``, ``load_cron_jobs`` and collaborates with
    ``get_data_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_data_dir() / "cron_jobs.json"


def get_project_config_dir(cwd: str | Path) -> Path:
    """Return the per-project .openharness directory.

    Integration: Called by ``create_default_command_registry``,
    ``create_default_command_registry._init_handler`` and collaborates with
    ``project_dir.mkdir``, ``resolve``, ``Path``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    project_dir = Path(cwd).resolve() / ".openharness"
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def get_project_issue_file(cwd: str | Path) -> Path:
    """Return the per-project issue context file.

    Integration: Called by ``_setup_issue_pr_context_flow``, ``create_default_command_registry``
    and collaborates with ``get_project_config_dir``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_project_config_dir(cwd) / "issue.md"


def get_project_pr_comments_file(cwd: str | Path) -> Path:
    """Return the per-project PR comments context file.

    Integration: Called by ``_setup_issue_pr_context_flow``, ``create_default_command_registry``
    and collaborates with ``get_project_config_dir``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_project_config_dir(cwd) / "pr_comments.md"


def get_project_autopilot_dir(cwd: str | Path) -> Path:
    """Return the per-project autopilot state directory.

    Integration: Called by ``get_project_autopilot_registry_path``,
    ``get_project_repo_journal_path`` and collaborates with ``autopilot_dir.mkdir``,
    ``get_project_config_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    autopilot_dir = get_project_config_dir(cwd) / "autopilot"
    autopilot_dir.mkdir(parents=True, exist_ok=True)
    return autopilot_dir


def get_project_autopilot_registry_path(cwd: str | Path) -> Path:
    """Return the autopilot task registry path.

    Integration: Called by ``RepoAutopilotStore.__init__`` and collaborates with
    ``get_project_autopilot_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_project_autopilot_dir(cwd) / "registry.json"


def get_project_repo_journal_path(cwd: str | Path) -> Path:
    """Return the append-only repo journal path.

    Integration: Called by ``RepoAutopilotStore.__init__`` and collaborates with
    ``get_project_autopilot_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_project_autopilot_dir(cwd) / "repo_journal.jsonl"


def get_project_active_repo_context_path(cwd: str | Path) -> Path:
    """Return the synthesized active repo context path.

    Integration: Called by ``RepoAutopilotStore.__init__``, ``build_runtime_system_prompt`` and
    collaborates with ``get_project_autopilot_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_project_autopilot_dir(cwd) / "active_repo_context.md"


def get_project_autopilot_policy_path(cwd: str | Path) -> Path:
    """Return the autopilot policy path.

    Integration: Called by ``RepoAutopilotStore.rebuild_active_context``,
    ``RepoAutopilotStore.load_policies`` and collaborates with ``get_project_autopilot_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_project_autopilot_dir(cwd) / "autopilot_policy.yaml"


def get_project_verification_policy_path(cwd: str | Path) -> Path:
    """Return the verification policy path.

    Integration: Called by ``RepoAutopilotStore.rebuild_active_context``,
    ``RepoAutopilotStore.load_policies`` and collaborates with ``get_project_autopilot_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_project_autopilot_dir(cwd) / "verification_policy.yaml"


def get_project_release_policy_path(cwd: str | Path) -> Path:
    """Return the release policy path.

    Integration: Called by ``RepoAutopilotStore.rebuild_active_context``,
    ``RepoAutopilotStore.load_policies`` and collaborates with ``get_project_autopilot_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return get_project_autopilot_dir(cwd) / "release_policy.yaml"


def get_project_autopilot_runs_dir(cwd: str | Path) -> Path:
    """Return the autopilot run artifacts directory.

    Integration: Called by ``RepoAutopilotStore.__init__`` and collaborates with
    ``runs_dir.mkdir``, ``get_project_autopilot_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    runs_dir = get_project_autopilot_dir(cwd) / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    return runs_dir
