"""Entry point for `python -m openharness`.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from openharness.cli import app

if __name__ == "__main__":
    app()
