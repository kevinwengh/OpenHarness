"""Local cron-style registry helpers.

Integration: This module participates in runtime support services such as compaction, sessions,
cron, extraction, and autodream.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve persistence schemas, task/time bounds, compaction continuity,
cancellation, atomic writes, and best-effort failure boundaries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from croniter import croniter

from openharness.config.paths import get_cron_registry_path
from openharness.utils.file_lock import exclusive_file_lock
from openharness.utils.fs import atomic_write_text


def _cron_lock_path() -> Path:
    """Return the filesystem path for cron lock.

    Integration: Called by ``upsert_cron_job``, ``delete_cron_job`` and collaborates with
    ``get_cron_registry_path``, ``path.with_suffix``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    path = get_cron_registry_path()
    return path.with_suffix(path.suffix + ".lock")


def load_cron_jobs() -> list[dict[str, Any]]:
    """Load stored cron jobs.

    Integration: Called by ``cron_list_cmd``, ``upsert_cron_job`` and collaborates with
    ``get_cron_registry_path``, ``path.exists``, ``json.loads``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    exception and fallback behavior expected by callers.
    """
    path = get_cron_registry_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def save_cron_jobs(jobs: list[dict[str, Any]]) -> None:
    """Persist cron jobs to disk.

    Integration: Called by ``upsert_cron_job``, ``delete_cron_job`` and collaborates with
    ``atomic_write_text``, ``get_cron_registry_path``, ``json.dumps``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    atomic_write_text(
        get_cron_registry_path(),
        json.dumps(jobs, indent=2) + "\n",
    )


def validate_cron_expression(expression: str) -> bool:
    """Return True if the expression is a valid cron schedule.

    Integration: Called by ``upsert_cron_job``, ``mark_job_run`` and collaborates with
    ``croniter.is_valid``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return croniter.is_valid(expression)


def validate_timezone(tz: str | None) -> bool:
    """Return True if *tz* is a valid IANA timezone or empty.

    Integration: Called by ``CronCreateTool.execute`` and collaborates with ``ZoneInfo``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if not tz:
        return True
    try:
        ZoneInfo(tz)
    except Exception:
        return False
    return True


def next_run_time(expression: str, base: datetime | None = None, tz: str | None = None) -> datetime:
    """Return the next run time for a cron expression.

    The returned datetime is always UTC. If *tz* is provided, the cron expression
    is interpreted in that IANA timezone.

    Integration: Called by ``upsert_cron_job``, ``mark_job_run`` and collaborates with
    ``get_next``, ``datetime.now``, ``base.astimezone``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    base = base or datetime.now(timezone.utc)
    if tz:
        local_base = base.astimezone(ZoneInfo(tz))
        local_next = croniter(expression, local_base).get_next(datetime)
        return local_next.astimezone(timezone.utc)
    return croniter(expression, base).get_next(datetime)


def upsert_cron_job(job: dict[str, Any]) -> None:
    """Insert or replace one cron job.

    Automatically sets ``enabled`` to True and computes ``next_run`` when the
    schedule is a valid cron expression.

    Integration: Called by ``RepoAutopilotStore.install_default_cron``,
    ``CronCreateTool.execute`` and collaborates with ``job.setdefault``, ``job.get``,
    ``validate_cron_expression``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking; retain lock scope and release behavior.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    job.setdefault("enabled", True)
    job.setdefault("created_at", datetime.now(timezone.utc).isoformat())

    schedule = job.get("schedule", "")
    if validate_cron_expression(schedule):
        job["next_run"] = next_run_time(schedule, tz=job.get("timezone") or job.get("tz")).isoformat()

    with exclusive_file_lock(_cron_lock_path()):
        jobs = [existing for existing in load_cron_jobs() if existing.get("name") != job.get("name")]
        jobs.append(job)
        jobs.sort(key=lambda item: str(item.get("name", "")))
        save_cron_jobs(jobs)


def delete_cron_job(name: str) -> bool:
    """Delete one cron job by name.

    Integration: Called by ``CronDeleteTool.execute`` and collaborates with
    ``exclusive_file_lock``, ``load_cron_jobs``, ``save_cron_jobs``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking; retain lock scope and release behavior.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    with exclusive_file_lock(_cron_lock_path()):
        jobs = load_cron_jobs()
        filtered = [job for job in jobs if job.get("name") != name]
        if len(filtered) == len(jobs):
            return False
        save_cron_jobs(filtered)
    return True


def get_cron_job(name: str) -> dict[str, Any] | None:
    """Return one cron job by name.

    Integration: Called by ``RemoteTriggerTool.execute`` and collaborates with
    ``load_cron_jobs``, ``job.get``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    for job in load_cron_jobs():
        if job.get("name") == name:
            return job
    return None


def set_job_enabled(name: str, enabled: bool) -> bool:
    """Enable or disable a cron job. Returns False if job not found.

    Integration: Called by ``cron_toggle_cmd``, ``CronToggleTool.execute`` and collaborates with
    ``exclusive_file_lock``, ``load_cron_jobs``, ``_cron_lock_path``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking; retain lock scope and release behavior.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    with exclusive_file_lock(_cron_lock_path()):
        jobs = load_cron_jobs()
        for job in jobs:
            if job.get("name") == name:
                job["enabled"] = enabled
                save_cron_jobs(jobs)
                return True
    return False


def mark_job_run(name: str, *, success: bool) -> None:
    """Update last_run and recompute next_run after a job executes.

    Integration: Called by ``execute_job`` and collaborates with ``exclusive_file_lock``,
    ``load_cron_jobs``, ``datetime.now``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking; retain lock scope and release behavior.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    with exclusive_file_lock(_cron_lock_path()):
        jobs = load_cron_jobs()
        now = datetime.now(timezone.utc)
        for job in jobs:
            if job.get("name") == name:
                job["last_run"] = now.isoformat()
                job["last_status"] = "success" if success else "failed"
                schedule = job.get("schedule", "")
                if validate_cron_expression(schedule):
                    job["next_run"] = next_run_time(schedule, now, tz=job.get("timezone") or job.get("tz")).isoformat()
                save_cron_jobs(jobs)
                return
