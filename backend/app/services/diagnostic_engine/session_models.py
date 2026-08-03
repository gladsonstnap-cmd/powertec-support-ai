from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.services.diagnostic_engine.decision_models import Decision
from app.services.diagnostic_engine.evidence_models import Evidence
from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.knowledge_models import KnowledgeSearchResult
from app.services.diagnostic_engine.memory_models import MemorySnapshot
from app.services.diagnostic_engine.models import IncidentClassification, IntentClassification
from app.services.diagnostic_engine.planner_models import DiagnosticPlan, DiagnosticPlanResult
from app.services.diagnostic_engine.workflow_models import WorkflowResult


class DiagnosticSessionStatus(StrEnum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    WAITING_USER = "WAITING_USER"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    READY_FOR_TEST = "READY_FOR_TEST"
    READY_FOR_ACTION = "READY_FOR_ACTION"
    ESCALATED = "ESCALATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class DiagnosticSession:
    """Immutable session snapshot. The initial interaction count is zero."""

    session_id: str
    status: DiagnosticSessionStatus
    original_message: str
    last_message: str
    intent: IntentClassification | None = None
    incident: IncidentClassification | None = None
    knowledge_result: tuple[KnowledgeSearchResult, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    evidence_history: tuple[Evidence, ...] = ()
    decisions: tuple[Decision, ...] = ()
    questions_asked: tuple[str, ...] = ()
    answers: tuple[str, ...] = ()
    known_information: dict[str, object] = field(default_factory=dict)
    memory_snapshot: MemorySnapshot = field(default_factory=MemorySnapshot)
    diagnostic_plan: DiagnosticPlan | None = None
    planner_result: DiagnosticPlanResult | None = None
    unresolved_information: tuple[str, ...] = ()
    current_question: str | None = None
    user_confirmation: bool | None = None
    created_at_monotonic: float = 0.0
    updated_at_monotonic: float = 0.0
    interaction_count: int = 0
    metadata: dict[str, object] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "knowledge_result",
            "hypotheses",
            "evidence_history",
            "decisions",
            "questions_asked",
            "answers",
            "unresolved_information",
            "errors",
        ):
            object.__setattr__(self, name, tuple(deepcopy(getattr(self, name))))
        object.__setattr__(self, "known_information", deepcopy(dict(self.known_information)))
        object.__setattr__(self, "memory_snapshot", deepcopy(self.memory_snapshot))
        object.__setattr__(self, "diagnostic_plan", deepcopy(self.diagnostic_plan))
        object.__setattr__(self, "planner_result", deepcopy(self.planner_result))
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))


@dataclass(frozen=True)
class SessionTurnResult:
    session: DiagnosticSession
    workflow_result: WorkflowResult | None
    response_message: str
    next_expected_input: str | None
    state_changed: bool
    previous_status: DiagnosticSessionStatus
    current_status: DiagnosticSessionStatus
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "errors", tuple(self.errors))
