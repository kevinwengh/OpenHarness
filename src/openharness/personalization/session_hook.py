"""Session-end hook to extract and persist local environment rules.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

import logging

from openharness.engine.messages import ConversationMessage
from openharness.personalization.extractor import (
    extract_facts_from_text,
    facts_to_rules_markdown,
)
from openharness.personalization.rules import (
    load_facts,
    merge_facts,
    save_facts,
    save_local_rules,
)

log = logging.getLogger(__name__)


def update_rules_from_session(messages: list[ConversationMessage]) -> int:
    """Extract local facts from session messages and update rules.

    Called at session end. Returns the number of new facts extracted.

    Args:
        messages: The conversation messages from the session.

    Returns:
        Number of new facts found and persisted.

    Integration: Called by ``close_runtime`` and collaborates with ``join``,
    ``extract_facts_from_text``, ``load_facts``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    # Collect all text from messages
    all_text = []
    for msg in messages:
        for block in msg.content:
            text = getattr(block, "text", None) or getattr(block, "content", None) or ""
            if isinstance(text, str) and text:
                all_text.append(text)

    if not all_text:
        return 0

    combined = "\n".join(all_text)
    new_facts = extract_facts_from_text(combined)
    if not new_facts:
        return 0

    # Merge with existing
    existing = load_facts()
    merged = merge_facts(existing, new_facts)
    save_facts(merged)

    # Regenerate rules markdown
    rules_md = facts_to_rules_markdown(merged["facts"])
    if rules_md:
        save_local_rules(rules_md)

    new_count = len(merged["facts"]) - len(existing.get("facts", []))
    log.info(
        "Personalization: %d new facts extracted (%d total)",
        max(new_count, 0),
        len(merged["facts"]),
    )
    return max(new_count, 0)
