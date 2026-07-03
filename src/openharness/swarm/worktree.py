"""Git worktree isolation for swarm agents.

Integration: This module participates in multi-agent team, mailbox, permission, subprocess, and
worktree coordination.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve identity and mailbox schemas, lock/atomicity, cancellation, permission
routing, Git isolation, and teardown.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------

_VALID_SEGMENT = re.compile(r"^[a-zA-Z0-9._-]+$")
_MAX_SLUG_LENGTH = 64
_COMMON_SYMLINK_DIRS = ("node_modules", ".venv", "__pycache__", ".tox")


def validate_worktree_slug(slug: str) -> str:
    """Sanitize and validate a worktree slug.

    Rules:
    - Max 64 characters total
    - Each '/'-separated segment must match [a-zA-Z0-9._-]+
    - '.' and '..' segments are rejected (path traversal)
    - Leading/trailing '/' are rejected

    Returns the slug unchanged if valid, raises ValueError otherwise.

    Integration: Called by ``WorktreeManager.create_worktree``,
    ``WorktreeManager.remove_worktree`` and collaborates with ``slug.split``, ``ValueError``,
    ``slug.startswith``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if not slug:
        raise ValueError("Worktree slug must not be empty")

    if len(slug) > _MAX_SLUG_LENGTH:
        raise ValueError(
            f"Worktree slug must be {_MAX_SLUG_LENGTH} characters or fewer (got {len(slug)})"
        )

    # Reject absolute paths
    if slug.startswith("/") or slug.startswith("\\"):
        raise ValueError(f"Worktree slug must not be an absolute path: {slug!r}")

    for segment in slug.split("/"):
        if segment in (".", ".."):
            raise ValueError(
                f'Worktree slug {slug!r}: must not contain "." or ".." path segments'
            )
        if not _VALID_SEGMENT.match(segment):
            raise ValueError(
                f"Worktree slug {slug!r}: each segment must be non-empty and contain only "
                "letters, digits, dots, underscores, and dashes"
            )

    return slug


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class WorktreeInfo:
    """Metadata about a managed git worktree.

    Integration: Constructed or referenced by ``WorktreeManager.create_worktree``,
    ``WorktreeManager.list_worktrees``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    slug: str
    path: Path
    branch: str
    original_path: Path
    created_at: float
    agent_id: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _flatten_slug(slug: str) -> str:
    """Replace '/' with '+' to avoid nested directory/branch issues.

    Integration: Called by ``_worktree_branch``, ``WorktreeManager.create_worktree`` and
    collaborates with ``slug.replace``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return slug.replace("/", "+")


def _worktree_branch(slug: str) -> str:
    """Derive worktree branch from the current inputs and subsystem state.

    Integration: Called by ``WorktreeManager.create_worktree`` and collaborates with
    ``_flatten_slug``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return f"worktree-{_flatten_slug(slug)}"


async def _run_git(*args: str, cwd: Path) -> tuple[int, str, str]:
    """Run a git command, returning (returncode, stdout, stderr).

    Integration: Used as an internal helper or callback at this module boundary and collaborates
    with ``asyncio.create_subprocess_exec``, ``proc.communicate``, ``strip``.

    Event loop: This coroutine awaits subprocess work; preserve process cleanup and avoid shell-
    blocking operations.

    Change safety: Preserve argv boundaries, timeouts, and child cleanup expected by callers.
    """
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""},
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout_bytes.decode(errors="replace").strip(),
        stderr_bytes.decode(errors="replace").strip(),
    )


async def _symlink_common_dirs(repo_path: Path, worktree_path: Path) -> None:
    """Symlink large common directories from the main repo to avoid duplication.

    Integration: Called by ``WorktreeManager.create_worktree`` and collaborates with
    ``dst.exists``, ``dst.is_symlink``, ``src.exists``.

    Event loop: This coroutine executes synchronously until it returns; filesystem or process
    work therefore runs inline on the caller's loop. Keep that work bounded or offload it before
    it can block.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    for dir_name in _COMMON_SYMLINK_DIRS:
        src = repo_path / dir_name
        dst = worktree_path / dir_name
        if dst.exists() or dst.is_symlink():
            continue
        if not src.exists():
            continue
        try:
            dst.symlink_to(src)
        except OSError:
            pass  # Non-fatal: disk full, unsupported fs, etc.


async def _remove_symlinks(worktree_path: Path) -> None:
    """Remove symlinks created by _symlink_common_dirs.

    Integration: Called by ``WorktreeManager.remove_worktree`` and collaborates with
    ``dst.is_symlink``, ``dst.unlink``.

    Event loop: This coroutine executes synchronously until it returns; filesystem or process
    work therefore runs inline on the caller's loop. Keep that work bounded or offload it before
    it can block.

    Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
    exception and fallback behavior expected by callers.
    """
    for dir_name in _COMMON_SYMLINK_DIRS:
        dst = worktree_path / dir_name
        if dst.is_symlink():
            try:
                dst.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# WorktreeManager
# ---------------------------------------------------------------------------

class WorktreeManager:
    """Manage git worktrees for isolated agent execution.

    Worktrees are stored under ``base_dir/<slug>/`` (with '/' replaced by
    '+' to keep the layout flat).  A JSON metadata file tracks active
    worktrees and their associated agent IDs so stale ones can be pruned.

    Integration: Constructed or referenced by ``RepoAutopilotStore.run_card``.

    Event loop: Async methods ``create_worktree``, ``remove_worktree``, ``list_worktrees``,
    ``cleanup_stale`` run on their caller's loop; instances must retain clear task,
    cancellation, and cleanup ownership.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        """Initialize ``WorktreeManager`` and bind its runtime dependencies.

        Integration: Exposed through ``WorktreeManager`` and collaborates with ``Path.home``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.base_dir: Path = base_dir or Path.home() / ".openharness" / "worktrees"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_worktree(
        self,
        repo_path: Path,
        slug: str,
        branch: str | None = None,
        agent_id: str | None = None,
    ) -> WorktreeInfo:
        """Create (or resume) a git worktree for *slug*.

        If the worktree directory already exists and is a valid git worktree,
        it is resumed without re-running ``git worktree add``.

        Args:
            repo_path: Absolute path to the main repository.
            slug: Human-readable identifier (validated via validate_worktree_slug).
            branch: Branch name to check out; defaults to a generated ``worktree-<slug>`` name.
            agent_id: Optional identifier of the agent that owns this worktree.

        Returns:
            WorktreeInfo describing the worktree.

        Integration: Called by ``RepoAutopilotStore.run_card`` and collaborates with
        ``validate_worktree_slug``, ``repo_path.resolve``, ``base_dir.mkdir``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve path isolation, encoding, and persistence side effects; preserve
        exception and fallback behavior expected by callers.
        """
        validate_worktree_slug(slug)
        repo_path = repo_path.resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

        flat_slug = _flatten_slug(slug)
        worktree_path = self.base_dir / flat_slug
        worktree_branch = branch or _worktree_branch(slug)

        # Fast resume: check whether the worktree is already registered
        if worktree_path.exists():
            code, _, _ = await _run_git(
                "rev-parse", "--git-dir", cwd=worktree_path
            )
            if code == 0:
                return WorktreeInfo(
                    slug=slug,
                    path=worktree_path,
                    branch=worktree_branch,
                    original_path=repo_path,
                    created_at=worktree_path.stat().st_mtime,
                    agent_id=agent_id,
                )

        # New worktree: -B resets an orphan branch left by a prior remove
        code, _, stderr = await _run_git(
            "worktree", "add", "-B", worktree_branch, str(worktree_path), "HEAD",
            cwd=repo_path,
        )
        if code != 0:
            raise RuntimeError(f"git worktree add failed: {stderr}")

        await _symlink_common_dirs(repo_path, worktree_path)

        return WorktreeInfo(
            slug=slug,
            path=worktree_path,
            branch=worktree_branch,
            original_path=repo_path,
            created_at=time.time(),
            agent_id=agent_id,
        )

    async def remove_worktree(self, slug: str) -> bool:
        """Remove a worktree by slug.

        Cleans up symlinks first, then runs ``git worktree remove --force``.

        Returns:
            True if the worktree was removed; False if it did not exist.

        Integration: Called by ``RepoAutopilotStore.run_card``,
        ``WorktreeManager.cleanup_stale`` and collaborates with ``validate_worktree_slug``,
        ``_flatten_slug``, ``worktree_path.exists``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        validate_worktree_slug(slug)
        flat_slug = _flatten_slug(slug)
        worktree_path = self.base_dir / flat_slug

        if not worktree_path.exists():
            return False

        # Remove symlinks before git removes the directory
        await _remove_symlinks(worktree_path)

        # Determine repo root from the worktree's git metadata
        code, git_common, _ = await _run_git(
            "rev-parse", "--git-common-dir", cwd=worktree_path
        )
        if code == 0 and git_common:
            # git_common points to .git inside the main repo
            repo_path = Path(git_common).resolve().parent
            if repo_path.exists():
                await _run_git(
                    "worktree", "remove", "--force", str(worktree_path),
                    cwd=repo_path,
                )
                return True

        # Fallback: try to remove via absolute path from any working directory
        # If repo_path detection failed, attempt removal with cwd=base_dir
        code, _, _ = await _run_git(
            "worktree", "remove", "--force", str(worktree_path),
            cwd=self.base_dir,
        )
        return code == 0

    async def list_worktrees(self) -> list[WorktreeInfo]:
        """Return WorktreeInfo for every known worktree under base_dir.

        Integration: Called by ``WorktreeManager.cleanup_stale`` and collaborates with
        ``base_dir.iterdir``, ``base_dir.exists``, ``child.name.replace``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        if not self.base_dir.exists():
            return []

        results: list[WorktreeInfo] = []
        for child in self.base_dir.iterdir():
            if not child.is_dir():
                continue
            code, _, _ = await _run_git("rev-parse", "--git-dir", cwd=child)
            if code != 0:
                continue

            # Recover branch name from HEAD
            rc, branch_out, _ = await _run_git(
                "rev-parse", "--abbrev-ref", "HEAD", cwd=child
            )
            branch = branch_out if rc == 0 else "unknown"

            # Recover original repo path from git-common-dir
            rc2, common_dir, _ = await _run_git(
                "rev-parse", "--git-common-dir", cwd=child
            )
            if rc2 == 0 and common_dir:
                original_path = Path(common_dir).resolve().parent
            else:
                original_path = child

            # Slug is the directory name (flat form); restore '/' from '+'
            slug = child.name.replace("+", "/")
            results.append(
                WorktreeInfo(
                    slug=slug,
                    path=child,
                    branch=branch,
                    original_path=original_path,
                    created_at=child.stat().st_mtime,
                )
            )

        return results

    async def cleanup_stale(self, active_agent_ids: set[str] | None = None) -> list[str]:
        """Remove worktrees that have no active agent.

        Args:
            active_agent_ids: Set of agent IDs still running. If None,
                *all* worktrees with an agent_id are considered stale.

        Returns:
            List of slugs that were removed.

        Integration: Exposed as a public entrypoint for this subsystem and collaborates with
        ``list_worktrees``, ``remove_worktree``, ``removed.append``.

        Event loop: This coroutine awaits collaborators on the caller's loop and must avoid
        blocking I/O.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        worktrees = await self.list_worktrees()
        removed: list[str] = []
        for info in worktrees:
            if info.agent_id is None:
                continue
            if active_agent_ids is not None and info.agent_id in active_agent_ids:
                continue
            ok = await self.remove_worktree(info.slug)
            if ok:
                removed.append(info.slug)
        return removed
