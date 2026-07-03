"""System prompt builder for OpenHarness.

Integration: This module participates in the shared OpenHarness runtime.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from openharness.prompts.claudemd import discover_claude_md_files, load_claude_md_prompt
from openharness.prompts.context import build_runtime_system_prompt
from openharness.prompts.system_prompt import build_system_prompt
from openharness.prompts.environment import get_environment_info

__all__ = [
    "build_runtime_system_prompt",
    "build_system_prompt",
    "discover_claude_md_files",
    "get_environment_info",
    "load_claude_md_prompt",
]
