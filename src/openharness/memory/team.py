"""Local team-memory vault helpers and safety guards.

Integration: This module participates in durable project memory selection, indexing, migration,
and usage metadata.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve project scoping, bounded prompt content, deterministic schemas, atomic
updates, and separation from session/personal memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from openharness.memory.paths import get_project_memory_dir
from openharness.memory.schema import path_is_relative_to

TEAM_DIR_NAME = "team"
MEMORY_INDEX = "MEMORY.md"


@dataclass(frozen=True)
class SecretMatch:
    """A possible secret found in shared memory content.

    Integration: Constructed or referenced by ``scan_for_secrets``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    rule_id: str
    label: str


SECRET_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("private-key", "private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws-access-key", "AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", "GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai-key", "OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("anthropic-key", "Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("generic-secret", "secret assignment", re.compile(r"(?i)\b(secret|token|api[_-]?key|password)\s*[:=]\s*['\"]?[^'\"\s]{12,}")),
)


def get_team_memory_dir(cwd: str | Path) -> Path:
    """Return the project-local shared team memory vault.

    Integration: Called by ``_handle_memory_team_command``, ``ensure_team_memory_vault`` and
    collaborates with ``get_project_memory_dir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    return get_project_memory_dir(cwd) / TEAM_DIR_NAME


def ensure_team_memory_vault(cwd: str | Path) -> Path:
    """Create and return the team memory vault.

    Integration: Called by ``_handle_memory_team_command``, ``add_memory_entry`` and
    collaborates with ``get_team_memory_dir``, ``team_dir.mkdir``, ``entrypoint.exists``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """

    team_dir = get_team_memory_dir(cwd)
    team_dir.mkdir(parents=True, exist_ok=True)
    entrypoint = team_dir / MEMORY_INDEX
    if not entrypoint.exists():
        entrypoint.write_text("# Memory Index\n", encoding="utf-8")
    return team_dir


def validate_team_memory_write_path(cwd: str | Path, candidate: str | Path) -> tuple[Path | None, str | None]:
    """Validate a write target against traversal and symlink escape.

    Integration: Called by ``apply_extraction_records`` and collaborates with ``resolve``,
    ``expanduser``, ``path.resolve``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    team_dir = ensure_team_memory_vault(cwd).resolve()
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = team_dir / path
    resolved = path.resolve()
    if not path_is_relative_to(resolved, team_dir):
        return None, f"Path escapes team memory directory: {candidate}"
    parent = resolved.parent
    deepest = parent
    while not deepest.exists() and deepest != deepest.parent:
        deepest = deepest.parent
    if deepest.exists() and not path_is_relative_to(deepest.resolve(), team_dir):
        return None, f"Path escapes team memory directory via symlink: {candidate}"
    return resolved, None


def scan_for_secrets(content: str) -> list[SecretMatch]:
    """Return possible secrets in content without exposing matched values.

    Integration: Called by ``check_team_memory_secrets`` and collaborates with
    ``pattern.search``, ``matches.append``, ``SecretMatch``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    matches: list[SecretMatch] = []
    for rule_id, label, pattern in SECRET_RULES:
        if pattern.search(content):
            matches.append(SecretMatch(rule_id=rule_id, label=label))
    return matches


def check_team_memory_secrets(content: str) -> str | None:
    """Return an error message when shared memory content appears sensitive.

    Integration: Called by ``_handle_memory_validate_command``, ``_handle_memory_team_command``
    and collaborates with ``scan_for_secrets``, ``join``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """

    matches = scan_for_secrets(content)
    if not matches:
        return None
    labels = ", ".join(match.label for match in matches)
    return (
        f"Content contains potential secrets ({labels}) and cannot be written to team memory. "
        "Team memory is shared with project collaborators."
    )
