"""OpenHarness sandbox integration helpers.

Integration: This module participates in isolated execution selected by runtime/tool adapters.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve path validation, container lifecycle, network/resource limits, command
fidelity, and cleanup.
"""

from openharness.sandbox.adapter import (
    SandboxAvailability,
    SandboxUnavailableError,
    build_sandbox_runtime_config,
    get_sandbox_availability,
    wrap_command_for_sandbox,
)
from openharness.sandbox.docker_backend import DockerSandboxSession, get_docker_availability
from openharness.sandbox.path_validator import validate_sandbox_path
from openharness.sandbox.session import (
    get_docker_sandbox,
    is_docker_sandbox_active,
    start_docker_sandbox,
    stop_docker_sandbox,
)

__all__ = [
    "DockerSandboxSession",
    "SandboxAvailability",
    "SandboxUnavailableError",
    "build_sandbox_runtime_config",
    "get_docker_availability",
    "get_docker_sandbox",
    "get_sandbox_availability",
    "is_docker_sandbox_active",
    "start_docker_sandbox",
    "stop_docker_sandbox",
    "validate_sandbox_path",
    "wrap_command_for_sandbox",
]
