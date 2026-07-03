"""Cross-subsystem helpers with no runtime-composition ownership.

Utilities may be called from synchronous and asynchronous paths, so additions
should remain bounded, avoid hidden global state, and leave policy, persistence,
and resource lifecycle decisions in their owning subsystems.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""
