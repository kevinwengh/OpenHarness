"""Local rules file management.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_RULES_DIR = Path("~/.openharness/local_rules").expanduser()
_RULES_FILE = _RULES_DIR / "rules.md"
_FACTS_FILE = _RULES_DIR / "facts.json"


def _ensure_dir() -> None:
    """Ensure directory for the enclosing subsystem.

    Integration: Called by ``save_local_rules``, ``save_facts`` and collaborates with
    ``_RULES_DIR.mkdir``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    _RULES_DIR.mkdir(parents=True, exist_ok=True)


def load_local_rules() -> str:
    """Load the local rules markdown, or empty string if none exist.

    Integration: Called by ``build_runtime_system_prompt`` and collaborates with
    ``_RULES_FILE.exists``, ``strip``, ``_RULES_FILE.read_text``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    if _RULES_FILE.exists():
        return _RULES_FILE.read_text(encoding="utf-8").strip()
    return ""


def save_local_rules(content: str) -> Path:
    """Write local rules markdown.

    Integration: Called by ``update_rules_from_session`` and collaborates with ``_ensure_dir``,
    ``_RULES_FILE.write_text``, ``content.strip``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    _ensure_dir()
    _RULES_FILE.write_text(content.strip() + "\n", encoding="utf-8")
    return _RULES_FILE


def load_facts() -> dict:
    """Load extracted facts as a dict.

    Integration: Called by ``update_rules_from_session`` and collaborates with
    ``_FACTS_FILE.exists``, ``json.loads``, ``_FACTS_FILE.read_text``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    if _FACTS_FILE.exists():
        return json.loads(_FACTS_FILE.read_text(encoding="utf-8"))
    return {"facts": [], "last_updated": None}


def save_facts(facts: dict) -> None:
    """Persist extracted facts.

    Integration: Called by ``update_rules_from_session`` and collaborates with ``_ensure_dir``,
    ``isoformat``, ``_FACTS_FILE.write_text``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve path isolation, encoding, and persistence side effects expected by
    callers.
    """
    _ensure_dir()
    facts["last_updated"] = datetime.now(timezone.utc).isoformat()
    _FACTS_FILE.write_text(
        json.dumps(facts, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def merge_facts(existing: dict, new_facts: list[dict]) -> dict:
    """Merge new facts into existing, deduplicating by key.

    Integration: Called by ``update_rules_from_session`` and collaborates with ``existing.get``,
    ``f.get``, ``by_key.values``.

    Concurrency: This is synchronous; preserve deterministic behavior for its direct callers.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    by_key = {}
    for f in existing.get("facts", []):
        by_key[f["key"]] = f
    for f in new_facts:
        key = f.get("key", "")
        if key:
            if key in by_key:
                # Update with newer value, keep higher confidence
                old = by_key[key]
                if f.get("confidence", 0) >= old.get("confidence", 0):
                    by_key[key] = f
            else:
                by_key[key] = f
    return {"facts": list(by_key.values())}
