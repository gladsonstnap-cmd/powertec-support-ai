from dataclasses import dataclass, field

from app.services.diagnostic_engine.enums import ClassifierSource, IncidentCategory, IntentType, SeverityLevel


@dataclass(frozen=True)
class IntentClassification:
    intent: IntentType
    confidence: float
    source: ClassifierSource
    matched_terms: list[str]
    normalized_text: str


@dataclass(frozen=True)
class IncidentClassification:
    category: IncidentCategory
    confidence: float
    severity: SeverityLevel
    source: ClassifierSource
    matched_terms: list[str]
    normalized_text: str
    requires_human: bool
    requires_remote_diagnostic: bool
    rationale: str | None = None


@dataclass(frozen=True)
class DiagnosticContext:
    message: str
    customer_id: str | None = None
    ticket_id: str | None = None
    session_id: str | None = None
    pdv_system: str | None = None
    company: str | None = None
    branch: str | None = None
    affected_terminal: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    affected_scope: str | None = None
    collected_data: dict = field(default_factory=dict)
