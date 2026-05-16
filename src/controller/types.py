"""Data types for vafi controller.

These types define the interface between the controller and work sources.
They are shared across the controller, WorkSource protocol, and VtfWorkSource
implementation.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class AgentInfo:
    """Information about a registered agent."""
    id: str
    token: str


@dataclass
class RepoInfo:
    """Repository information for task execution."""
    url: str          # git clone URL
    branch: str       # default branch


@dataclass
class TaskInfo:
    """Task information from the work source."""
    id: str
    title: str
    spec: str         # YAML spec content
    project_id: str
    test_command: dict[str, Any]
    needs_review: bool
    assigned_to: str | None
    # vfobs observability dimension. Defaulted (NOT required) so the
    # existing TaskInfo(...) constructions in vafi tests don't
    # regress (verifier V16 / WG2 D-T0-1 lesson). vtaskforge has no
    # "workgraph" — its unit is the milestone; the vtf worksource
    # maps task.milestone.id here. Empty ⇒ emission hooks skip +
    # log once (degrade, never crash).
    workgraph_id: str = ""


@dataclass
class ReworkContext:
    """Context for rework execution."""
    session_id: str | None     # from previous execution, for --resume
    judge_feedback: str        # latest review with changes_requested
    attempt_number: int        # how many times rejected so far


@dataclass
class GateResult:
    """Result of a verification gate."""
    name: str
    command: str
    exit_code: int
    stdout: str
    passed: bool


@dataclass
class ExecutionResult:
    """Result of task execution."""
    success: bool              # all gates passed
    session_id: str | None     # harness session ID for future rework
    completion_report: str     # harness result text (opaque to controller)
    cost_usd: float
    num_turns: int
    gate_results: list[GateResult]