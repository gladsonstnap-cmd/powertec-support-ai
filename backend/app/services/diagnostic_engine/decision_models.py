from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence

from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.evidence_models import EvidenceResult, HypothesisUpdate
from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.models import DiagnosticContext


class DecisionType(StrEnum):
    ASK_QUESTION = "ASK_QUESTION"
    RUN_TEST = "RUN_TEST"
    RECOMMEND_ACTION = "RECOMMEND_ACTION"
    REQUEST_CONFIRMATION = "REQUEST_CONFIRMATION"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"
    COMPLETE = "COMPLETE"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


class DecisionPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Decision:
    decision_type: DecisionType
    priority: DecisionPriority
    title: str
    message: str
    reasoning: tuple[str, ...]
    confidence: float
    incident_id: str | None
    requires_human: bool
    risk_level: RiskLevel
    next_question: str | None
    recommended_test: str | None
    recommended_action: str | None
    confirmation_required: bool
    completion_reason: str | None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", max(0.0, min(1.0, self.confidence)))
        object.__setattr__(self, "reasoning", tuple(self.reasoning))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class DecisionInput:
    hypotheses: Sequence[Hypothesis | HypothesisUpdate]
    evidence_result: EvidenceResult | None = None
    diagnostic_context: DiagnosticContext | None = None
    previous_decisions: tuple[Decision, ...] = ()
    user_confirmation: bool | None = None
    max_questions_reached: bool = False
    max_tests_reached: bool = False
