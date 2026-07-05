"""Typed, side-effect-free foundations for OpenHarness automation workflows."""

from openharness.automation.loader import (
    DefinitionDiagnostic,
    DefinitionLoadResult,
    load_workflow_definitions,
)
from openharness.automation.concurrency import ConcurrencyLease, WorkflowConcurrencyCoordinator
from openharness.automation.matcher import MatchTrace, evaluate_condition, match_workflow
from openharness.automation.models import (
    ActionStep,
    AgentStep,
    ApprovalStep,
    AutomationEvent,
    WorkflowDefinition,
    definition_revision,
)
from openharness.automation.state import RunError, TransitionError, WorkflowRun
from openharness.automation.store import AutomationStore, AutomationStoreError, ReservationResult
from openharness.automation.templates import TemplateRenderError, render_template

__all__ = [
    "ActionStep",
    "AgentStep",
    "ApprovalStep",
    "AutomationEvent",
    "AutomationStore",
    "AutomationStoreError",
    "ConcurrencyLease",
    "DefinitionDiagnostic",
    "DefinitionLoadResult",
    "MatchTrace",
    "ReservationResult",
    "RunError",
    "TemplateRenderError",
    "TransitionError",
    "WorkflowDefinition",
    "WorkflowConcurrencyCoordinator",
    "WorkflowRun",
    "definition_revision",
    "evaluate_condition",
    "load_workflow_definitions",
    "match_workflow",
    "render_template",
]
