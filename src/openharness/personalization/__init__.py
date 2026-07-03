"""Session personalization — auto-extract local rules from conversation history.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from openharness.personalization.extractor import extract_local_rules
from openharness.personalization.rules import load_local_rules, save_local_rules

__all__ = ["extract_local_rules", "load_local_rules", "save_local_rules"]
