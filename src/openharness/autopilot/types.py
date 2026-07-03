"""Repo autopilot data models.

Integration: This module participates in repository task intake, policy, execution,
verification, PR, journal, and dashboard export.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve state-machine transitions, Git/worktree safety, retries, human gates,
idempotent comments, and atomic artifacts.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RepoTaskStatus = Literal[
    "queued",
    "accepted",
    "preparing",
    "running",
    "verifying",
    "pr_open",
    "waiting_ci",
    "repairing",
    "completed",
    "merged",
    "failed",
    "rejected",
    "superseded",
]
RepoTaskSource = Literal[
    "ohmo_request",
    "manual_idea",
    "github_issue",
    "github_pr",
    "claude_code_candidate",
]


class RepoTaskCard(BaseModel):
    """One normalized repo-level work item.

    Integration: Constructed or referenced by ``RepoAutopilotStore.enqueue_card``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    id: str
    fingerprint: str
    title: str
    body: str = ""
    source_kind: RepoTaskSource
    source_ref: str = ""
    status: RepoTaskStatus = "queued"
    score: int = 0
    score_reasons: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float
    updated_at: float


class RepoJournalEntry(BaseModel):
    """Append-only repo journal event.

    Integration: Constructed or referenced by ``RepoAutopilotStore.append_journal``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    timestamp: float
    kind: str
    summary: str
    task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepoAutopilotRegistry(BaseModel):
    """Full registry payload.

    Integration: Constructed or referenced by ``RepoAutopilotStore._ensure_layout``,
    ``RepoAutopilotStore._load_registry``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    version: int = 1
    updated_at: float = 0.0
    cards: list[RepoTaskCard] = Field(default_factory=list)


class RepoVerificationStep(BaseModel):
    """One verification command result.

    Integration: Constructed or referenced by ``RepoAutopilotStore._run_verification_steps``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    command: str
    returncode: int
    status: Literal["success", "failed", "skipped", "error"]
    stdout: str = ""
    stderr: str = ""


class RepoRunResult(BaseModel):
    """Result of one autopilot execution attempt.

    Integration: Constructed or referenced by ``RepoAutopilotStore.run_card``,
    ``RepoAutopilotStore._process_existing_pr_card``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Treat field names, defaults, validators, and serialized values as a
    compatibility contract for every producer and consumer.
    """

    card_id: str
    status: RepoTaskStatus
    assistant_summary: str = ""
    run_report_path: str = ""
    verification_report_path: str = ""
    verification_steps: list[RepoVerificationStep] = Field(default_factory=list)
    attempt_count: int = 0
    worktree_path: str = ""
    pr_number: int | None = None
    pr_url: str = ""
