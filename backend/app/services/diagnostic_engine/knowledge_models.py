from dataclasses import dataclass, field

from app.services.diagnostic_engine.enums import IncidentCategory, RiskLevel, SeverityLevel


class KnowledgeValidationError(ValueError):
    """Raised when the diagnostic knowledge base has invalid structured data."""


@dataclass(frozen=True)
class KnowledgeCause:
    id: str
    description: str
    base_confidence: float
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    risk_level: RiskLevel


@dataclass(frozen=True)
class DiagnosticQuestion:
    id: str
    text: str
    field: str
    priority: int
    answer_type: str
    options: list[str] = field(default_factory=list)
    required: bool = False


@dataclass(frozen=True)
class DiagnosticTest:
    id: str
    title: str
    description: str
    tool_name: str
    risk_level: RiskLevel
    requires_remote_agent: bool
    requires_approval: bool
    expected_results: list[str]


@dataclass(frozen=True)
class DiagnosticAction:
    id: str
    title: str
    description: str
    tool_name: str
    risk_level: RiskLevel
    requires_approval: bool
    requires_human: bool


@dataclass(frozen=True)
class KnowledgeIncident:
    id: str
    title: str
    description: str
    category: IncidentCategory
    default_severity: SeverityLevel
    symptoms: list[str]
    possible_causes: list[KnowledgeCause]
    questions: list[DiagnosticQuestion]
    recommended_tests: list[DiagnosticTest]
    recommended_actions: list[DiagnosticAction]
    required_information: list[str]
    escalation_conditions: list[str]
    requires_remote_diagnostic: bool
    requires_human: bool
    tags: list[str]


@dataclass(frozen=True)
class KnowledgeSearchResult:
    incident: KnowledgeIncident
    score: float
    matched_terms: list[str]
    rationale: str
