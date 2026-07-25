from app.services.diagnostic_engine.enums import IncidentCategory, RiskLevel
from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.knowledge_base import KnowledgeBase
from app.services.diagnostic_engine.knowledge_models import DiagnosticAction, DiagnosticTest, KnowledgeIncident
from app.services.diagnostic_engine.question_selector import QuestionSelector
from app.services.diagnostic_engine.scoring import HypothesisScorer


class HypothesisEngine:
    def __init__(
        self,
        knowledge_base: KnowledgeBase | None = None,
        scorer: HypothesisScorer | None = None,
        question_selector: QuestionSelector | None = None,
    ) -> None:
        self.knowledge_base = knowledge_base or KnowledgeBase.load_default()
        self.scorer = scorer or HypothesisScorer()
        self.question_selector = question_selector or QuestionSelector()

    def generate(
        self,
        message: str,
        identified_category: IncidentCategory | None,
        *,
        limit: int = 5,
        known_information: dict[str, object] | None = None,
        asked_question_ids: set[str] | None = None,
    ) -> list[Hypothesis]:
        if limit <= 0:
            return []

        hypotheses: list[Hypothesis] = []
        for incident in self.knowledge_base.list_all():
            score = self.scorer.score(message, incident, identified_category)
            if score.confidence <= 0:
                continue

            next_question = self.question_selector.select_next_question(
                incident,
                known_information=known_information,
                asked_question_ids=asked_question_ids,
            )
            hypotheses.append(
                Hypothesis(
                    incident_id=incident.id,
                    incident=incident,
                    confidence=score.confidence,
                    matched_terms=score.matched_terms,
                    matched_symptoms=score.matched_symptoms,
                    matched_tags=score.matched_tags,
                    matched_causes=score.matched_causes,
                    reasoning=score.reasoning,
                    supporting_evidence=score.supporting_evidence,
                    missing_information=self._missing_information(incident, known_information),
                    next_questions=[next_question] if next_question else [],
                    recommended_tests=incident.recommended_tests,
                    recommended_actions=incident.recommended_actions,
                    requires_human=incident.requires_human or any(action.requires_human for action in incident.recommended_actions),
                    risk_level=self._risk_level(incident),
                )
            )

        hypotheses.sort(key=lambda hypothesis: (-hypothesis.confidence, hypothesis.incident_id))
        return hypotheses[:limit]

    @staticmethod
    def _missing_information(
        incident: KnowledgeIncident,
        known_information: dict[str, object] | None,
    ) -> list[str]:
        known_information = known_information or {}
        known_values = {
            str(value).strip().lower()
            for value in known_information.values()
            if value is not None and str(value).strip()
        }
        return [
            information
            for information in incident.required_information
            if information.strip().lower() not in known_values
        ]

    def _risk_level(self, incident: KnowledgeIncident) -> RiskLevel:
        candidates = [
            *(test.risk_level for test in incident.recommended_tests),
            *(action.risk_level for action in incident.recommended_actions),
            *(cause.risk_level for cause in incident.possible_causes),
        ]
        return max(candidates, key=self._risk_rank)

    @staticmethod
    def _risk_rank(risk_level: RiskLevel) -> int:
        return {
            RiskLevel.READ_ONLY: 0,
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4,
        }[risk_level]
