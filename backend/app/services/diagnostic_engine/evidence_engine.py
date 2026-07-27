from dataclasses import replace

from app.services.diagnostic_engine.evidence_extractor import EvidenceExtractor
from app.services.diagnostic_engine.evidence_models import Evidence, EvidenceResult, EvidenceType, HypothesisUpdate
from app.services.diagnostic_engine.evidence_scoring import EvidenceScorer
from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.knowledge_base import KnowledgeBase
from app.services.diagnostic_engine.question_selector import QuestionSelector


class EvidenceEngine:
    def __init__(
        self,
        knowledge_base: KnowledgeBase | None = None,
        extractor: EvidenceExtractor | None = None,
        scorer: EvidenceScorer | None = None,
        question_selector: QuestionSelector | None = None,
    ) -> None:
        self.knowledge_base = knowledge_base or KnowledgeBase.load_default()
        self.extractor = extractor or EvidenceExtractor()
        self.scorer = scorer or EvidenceScorer()
        self.question_selector = question_selector or QuestionSelector()

    def apply(
        self,
        hypotheses: list[Hypothesis],
        raw_text: str,
        *,
        source: EvidenceType = EvidenceType.USER_ANSWER,
        asked_question_ids: set[str] | None = None,
        known_information: dict[str, object] | None = None,
        evidence_history: list[Evidence] | None = None,
    ) -> EvidenceResult:
        asked_question_ids = set(asked_question_ids or set())
        known_information = dict(known_information or {})
        evidence_history = list(evidence_history or [])
        evidence = self.extractor.extract(raw_text, source)

        previous_ranks = {hypothesis.incident_id: index + 1 for index, hypothesis in enumerate(hypotheses)}
        if evidence.evidence_id in {item.evidence_id for item in evidence_history}:
            updated = self._refresh_questions(hypotheses, known_information, asked_question_ids)
            updates = [
                HypothesisUpdate(
                    incident_id=hypothesis.incident_id,
                    previous_confidence=hypothesis.confidence,
                    confidence_delta=0.0,
                    new_confidence=hypothesis.confidence,
                    evidence_applied=evidence,
                    reasoning=["evidencia ja aplicada anteriormente; confianca preservada"],
                    rank_before=previous_ranks[hypothesis.incident_id],
                    rank_after=previous_ranks[hypothesis.incident_id],
                )
                for hypothesis in updated
            ]
            return self._result(evidence, updated, updates, known_information, asked_question_ids, evidence_history)

        self._update_known_information(evidence, known_information, asked_question_ids)
        updated_hypotheses: list[Hypothesis] = []
        pending_updates: list[tuple[Hypothesis, float, list[str]]] = []

        for hypothesis in hypotheses:
            delta, reasoning = self.scorer.score(hypothesis, evidence)
            new_confidence = round(max(0.0, min(1.0, hypothesis.confidence + delta)), 4)
            updated_hypothesis = replace(
                hypothesis,
                confidence=new_confidence,
                supporting_evidence=self._append_evidence(hypothesis.supporting_evidence, evidence, delta),
                missing_information=self._missing_information(hypothesis, known_information),
            )
            pending_updates.append((updated_hypothesis, delta, reasoning))
            updated_hypotheses.append(updated_hypothesis)

        updated_hypotheses = self._refresh_questions(updated_hypotheses, known_information, asked_question_ids)
        updated_hypotheses.sort(key=lambda hypothesis: (-hypothesis.confidence, hypothesis.incident_id))
        new_ranks = {hypothesis.incident_id: index + 1 for index, hypothesis in enumerate(updated_hypotheses)}
        by_id = {hypothesis.incident_id: hypothesis for hypothesis in updated_hypotheses}
        updates = [
            HypothesisUpdate(
                incident_id=hypothesis.incident_id,
                previous_confidence=next(original.confidence for original in hypotheses if original.incident_id == hypothesis.incident_id),
                confidence_delta=delta,
                new_confidence=by_id[hypothesis.incident_id].confidence,
                evidence_applied=evidence,
                reasoning=reasoning,
                rank_before=previous_ranks[hypothesis.incident_id],
                rank_after=new_ranks[hypothesis.incident_id],
            )
            for hypothesis, delta, reasoning in pending_updates
        ]
        updates.sort(key=lambda update: update.incident_id)
        return self._result(evidence, updated_hypotheses, updates, known_information, asked_question_ids, [*evidence_history, evidence])

    def _refresh_questions(
        self,
        hypotheses: list[Hypothesis],
        known_information: dict[str, object],
        asked_question_ids: set[str],
    ) -> list[Hypothesis]:
        refreshed: list[Hypothesis] = []
        for hypothesis in hypotheses:
            question = self.question_selector.select_next_question(
                hypothesis.incident,
                known_information=known_information,
                asked_question_ids=asked_question_ids,
            )
            refreshed.append(
                replace(
                    hypothesis,
                    missing_information=self._missing_information(hypothesis, known_information),
                    next_questions=[question] if question else [],
                )
            )
        return refreshed

    @staticmethod
    def _update_known_information(
        evidence: Evidence,
        known_information: dict[str, object],
        asked_question_ids: set[str],
    ) -> None:
        if evidence.field_name and evidence.field_value:
            known_information[evidence.field_name] = evidence.field_value
        if evidence.field_name:
            asked_question_ids.add(evidence.field_name)

    @staticmethod
    def _missing_information(hypothesis: Hypothesis, known_information: dict[str, object]) -> list[str]:
        known_names = {key.strip().lower() for key in known_information}
        known_values = {str(value).strip().lower() for value in known_information.values() if value is not None and str(value).strip()}
        return [
            item for item in hypothesis.incident.required_information
            if item.strip().lower() not in known_names and item.strip().lower() not in known_values
        ]

    @staticmethod
    def _append_evidence(existing: list[str], evidence: Evidence, delta: float) -> list[str]:
        if delta == 0.0:
            return existing
        additions = [*existing, *evidence.reasoning]
        deduped: list[str] = []
        for item in additions:
            if item not in deduped:
                deduped.append(item)
        return deduped

    def _result(
        self,
        evidence: Evidence,
        updated_hypotheses: list[Hypothesis],
        updates: list[HypothesisUpdate],
        known_information: dict[str, object],
        asked_question_ids: set[str],
        evidence_history: list[Evidence],
    ) -> EvidenceResult:
        selected_question = None
        if updated_hypotheses:
            selected_question = self.question_selector.select_next_question(
                updated_hypotheses[0].incident,
                known_information=known_information,
                asked_question_ids=asked_question_ids,
            )
        unresolved = updated_hypotheses[0].missing_information if updated_hypotheses else []
        return EvidenceResult(
            evidence=evidence,
            updated_hypotheses=updated_hypotheses,
            hypothesis_updates=updates,
            selected_question=selected_question,
            known_information=known_information,
            unresolved_information=unresolved,
            evidence_history=evidence_history,
        )
