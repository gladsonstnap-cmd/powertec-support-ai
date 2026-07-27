from dataclasses import dataclass, field
from enum import StrEnum

from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.knowledge_models import DiagnosticQuestion
from app.services.diagnostic_engine.normalization import normalize_text


class EvidenceType(StrEnum):
    USER_ANSWER = "USER_ANSWER"
    TEST_RESULT = "TEST_RESULT"
    SYSTEM_OBSERVATION = "SYSTEM_OBSERVATION"
    TECHNICIAN_INPUT = "TECHNICIAN_INPUT"


class EvidencePolarity(StrEnum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source: EvidenceType
    raw_text: str
    normalized_text: str
    evidence_type: EvidenceType
    polarity: EvidencePolarity
    matched_terms: list[str]
    related_incident_ids: list[str]
    confidence_delta: float
    field_name: str | None
    field_value: str | None
    reasoning: list[str]

    @classmethod
    def neutral(cls, raw_text: str, source: EvidenceType = EvidenceType.USER_ANSWER) -> "Evidence":
        normalized = normalize_text(raw_text)
        return cls(
            evidence_id=f"{source.value}:{normalized}",
            source=source,
            raw_text=raw_text,
            normalized_text=normalized,
            evidence_type=source,
            polarity=EvidencePolarity.NEUTRAL,
            matched_terms=[],
            related_incident_ids=[],
            confidence_delta=0.0,
            field_name=None,
            field_value=None,
            reasoning=["evidencia neutra sem impacto na confianca"],
        )


@dataclass(frozen=True)
class HypothesisUpdate:
    incident_id: str
    previous_confidence: float
    confidence_delta: float
    new_confidence: float
    evidence_applied: Evidence
    reasoning: list[str]
    rank_before: int
    rank_after: int


@dataclass(frozen=True)
class EvidenceResult:
    evidence: Evidence
    updated_hypotheses: list[Hypothesis]
    hypothesis_updates: list[HypothesisUpdate]
    selected_question: DiagnosticQuestion | None
    known_information: dict[str, object]
    unresolved_information: list[str]
    evidence_history: list[Evidence] = field(default_factory=list)
