from app.services.diagnostic_engine.evidence_models import Evidence, EvidencePolarity
from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.normalization import normalize_text


class EvidenceScorer:
    def score(self, hypothesis: Hypothesis, evidence: Evidence) -> tuple[float, list[str]]:
        if evidence.polarity == EvidencePolarity.NEUTRAL:
            return 0.0, ["evidencia neutra sem alteracao de confianca"]

        relevance, reasons = self._relevance(hypothesis, evidence)
        if relevance <= 0:
            return 0.0, ["evidencia sem relacao direta com a hipotese"]

        delta = evidence.confidence_delta * relevance
        delta = max(-0.35, min(0.35, delta))
        if evidence.polarity == EvidencePolarity.SUPPORTING:
            reasons.insert(0, "evidencia favoravel aplicada")
        else:
            reasons.insert(0, "evidencia contraria aplicada")
        return round(delta, 4), reasons

    def _relevance(self, hypothesis: Hypothesis, evidence: Evidence) -> tuple[float, list[str]]:
        relevance = 0.0
        reasoning: list[str] = []

        if hypothesis.incident_id in evidence.related_incident_ids:
            relevance += 1.35
            reasoning.append("evidencia relacionada diretamente ao incidente")

        if (not evidence.related_incident_ids or hypothesis.incident_id in evidence.related_incident_ids) and hypothesis.incident.category in self._categories_from_evidence(evidence):
            relevance += 0.55
            reasoning.append("categoria da evidencia compativel")

        symptom_matches = self._matches(evidence.normalized_text, hypothesis.incident.symptoms)
        if symptom_matches:
            relevance += 0.25
            reasoning.append("sintoma da hipotese aparece na evidencia")

        cause_matches = self._matches(evidence.normalized_text, [cause.description for cause in hypothesis.incident.possible_causes])
        if cause_matches:
            relevance += 0.25
            reasoning.append("causa da hipotese aparece na evidencia")

        test_matches = self._matches(
            evidence.normalized_text,
            [test.title for test in hypothesis.recommended_tests] + [test.description for test in hypothesis.recommended_tests],
        )
        if test_matches:
            relevance += 0.15
            reasoning.append("resultado tem relacao com teste recomendado")

        tag_matches = self._matches(evidence.normalized_text, hypothesis.incident.tags)
        if tag_matches:
            relevance += 0.2
            reasoning.append("tag da hipotese aparece na evidencia")

        return min(1.25, relevance), reasoning

    @staticmethod
    def _matches(normalized_text: str, candidates: list[str]) -> list[str]:
        matches: list[str] = []
        for candidate in candidates:
            normalized = normalize_text(candidate)
            if normalized and (normalized in normalized_text or any(term in normalized_text for term in normalized.split() if len(term) >= 4)):
                matches.append(candidate)
        return matches

    @staticmethod
    def _categories_from_evidence(evidence: Evidence) -> set:
        from app.services.diagnostic_engine.evidence_extractor import RULES

        categories = set()
        for rule in RULES:
            if any(term in evidence.normalized_text for term in rule.terms):
                categories.update(rule.related_categories)
        return categories

