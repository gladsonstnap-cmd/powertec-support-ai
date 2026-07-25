from dataclasses import dataclass, field

from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.knowledge_models import (
    DiagnosticAction,
    DiagnosticQuestion,
    DiagnosticTest,
    KnowledgeCause,
    KnowledgeIncident,
)


@dataclass(frozen=True)
class Hypothesis:
    incident_id: str
    incident: KnowledgeIncident
    confidence: float
    matched_terms: list[str]
    matched_symptoms: list[str]
    matched_tags: list[str]
    matched_causes: list[KnowledgeCause]
    reasoning: list[str]
    supporting_evidence: list[str]
    missing_information: list[str]
    next_questions: list[DiagnosticQuestion]
    recommended_tests: list[DiagnosticTest]
    recommended_actions: list[DiagnosticAction]
    requires_human: bool
    risk_level: RiskLevel


@dataclass(frozen=True)
class HypothesisScore:
    confidence: float
    matched_terms: list[str]
    matched_symptoms: list[str] = field(default_factory=list)
    matched_tags: list[str] = field(default_factory=list)
    matched_causes: list[KnowledgeCause] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    supporting_evidence: list[str] = field(default_factory=list)
