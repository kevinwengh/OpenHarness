"""Run the OpenHarness memory schema migration from a source checkout.

Integration: This opt-in driver supports installation, migration, or manual/E2E validation
outside the deterministic unit-test runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve explicit prerequisites, isolated state, subprocess cleanup, bounded
waits, credential handling, and clear pass/fail diagnostics; never make normal tests depend on
live services.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openharness.memory.migrate import main


if __name__ == "__main__":
    raise SystemExit(main())
