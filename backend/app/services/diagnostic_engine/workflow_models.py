from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.services.diagnostic_engine.decision_models import Decision
from app.services.diagnostic_engine.evidence_models import EvidenceResult
from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.knowledge_models import KnowledgeSearchResult
from app.services.diagnostic_engine.models import IncidentClassification, IntentClassification


class WorkflowStep(StrEnum):
    INTENT = "INTENT"
    INCIDENT = "INCIDENT"
    KNOWLEDGE = "KNOWLEDGE"
    HYPOTHESIS = "HYPOTHESIS"
    EVIDENCE = "EVIDENCE"
    DECISION = "DECISION"
    COMPLETE = "COMPLETE"


@dataclass
class WorkflowResult:
    intent: IntentClassification | None = None
    incident: IncidentClassification | None = None
    knowledge_result: list[KnowledgeSearchResult] | None = None
    hypotheses: list[Hypothesis] = field(default_factory=list)
    evidence_result: EvidenceResult | None = None
    decision: Decision | None = None
    processing_time_ms: float = 0.0
    steps_executed: list[WorkflowStep] = field(default_factory=list)
    success: bool = False
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
