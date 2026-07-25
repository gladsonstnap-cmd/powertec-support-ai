from app.services.diagnostic_engine.enums import IncidentCategory
from app.services.diagnostic_engine.hypothesis_models import HypothesisScore
from app.services.diagnostic_engine.knowledge_models import KnowledgeCause, KnowledgeIncident
from app.services.diagnostic_engine.normalization import normalize_text


CATEGORY_HINTS: dict[IncidentCategory, tuple[str, ...]] = {
    IncidentCategory.PDV_STARTUP: ("nao abre", "nao inicia", "fecha ao abrir", "tela nao carrega"),
    IncidentCategory.UPDATE: ("atualizacao", "atualizar", "depois da atualizacao", "versao"),
    IncidentCategory.SERVER: ("todos os caixas", "loja parada", "servidor offline", "todos parados"),
    IncidentCategory.DATABASE: ("postgres", "postgresql", "banco", "base de dados", "connection refused"),
    IncidentCategory.PRINTER: ("impressora", "cupom nao sai", "spooler", "fila de impressao"),
    IncidentCategory.FISCAL: ("sefaz", "nfce", "nfc-e", "nota fiscal", "certificado digital", "xml"),
    IncidentCategory.TEF: ("pinpad", "tef", "cartao", "operadora"),
}


class HypothesisScorer:
    def score(
        self,
        message: str,
        incident: KnowledgeIncident,
        identified_category: IncidentCategory | None,
    ) -> HypothesisScore:
        normalized = normalize_text(message)
        terms = self._terms(normalized)
        if not terms:
            return HypothesisScore(confidence=0.0, matched_terms=[])

        matched_symptoms = self._matched_texts(normalized, incident.symptoms)
        matched_tags = self._matched_texts(normalized, incident.tags)
        matched_causes = self._matched_causes(normalized, terms, incident.possible_causes)
        matched_title_terms = self._matched_terms(normalized, terms, incident.title)
        matched_category_hints = self._matched_texts(normalized, CATEGORY_HINTS.get(incident.category, ()))

        score = 0.0
        reasoning: list[str] = []
        supporting_evidence: list[str] = []

        if identified_category and identified_category == incident.category:
            score += 0.28
            reasoning.append(f"categoria {incident.category.value} encontrada")

        if matched_category_hints:
            score += min(0.24, 0.12 * len(matched_category_hints))
            reasoning.append(f"{len(matched_category_hints)} pista(s) de categoria compativel")
            supporting_evidence.extend(matched_category_hints)

        if matched_symptoms:
            score += min(0.26, 0.09 * len(matched_symptoms))
            reasoning.append(f"{len(matched_symptoms)} sintoma(s) compativel(is)")
            supporting_evidence.extend(matched_symptoms)

        if matched_tags:
            score += min(0.16, 0.06 * len(matched_tags))
            reasoning.append(f"{len(matched_tags)} tag(s) encontrada(s)")

        if matched_causes:
            cause_score = sum(cause.base_confidence for cause in matched_causes) / len(matched_causes)
            score += min(0.16, 0.08 + cause_score * 0.08)
            reasoning.append(f"{len(matched_causes)} causa(s) provavel(is) encontrada(s)")
            for cause in matched_causes:
                supporting_evidence.extend(cause.supporting_evidence)

        if matched_title_terms:
            score += min(0.1, 0.04 * len(matched_title_terms))
            reasoning.append("titulo do incidente contem termo(s) da mensagem")

        matched_terms = sorted(
            {
                *matched_title_terms,
                *self._flatten_terms(matched_symptoms, normalized),
                *self._flatten_terms(matched_tags, normalized),
                *self._flatten_terms(matched_category_hints, normalized),
                *self._flatten_terms([cause.description for cause in matched_causes], normalized),
            }
        )

        if score >= 0.72:
            reasoning.append("incidente altamente compativel")
        elif score >= 0.45:
            reasoning.append("incidente parcialmente compativel")

        return HypothesisScore(
            confidence=round(min(score, 1.0), 4),
            matched_terms=matched_terms,
            matched_symptoms=matched_symptoms,
            matched_tags=matched_tags,
            matched_causes=matched_causes,
            reasoning=reasoning,
            supporting_evidence=self._dedupe(supporting_evidence),
        )

    @staticmethod
    def _terms(normalized: str) -> list[str]:
        return [term for term in normalized.split() if len(term) >= 2]

    @staticmethod
    def _matched_texts(normalized: str, candidates: tuple[str, ...] | list[str]) -> list[str]:
        matches: list[str] = []
        for candidate in candidates:
            normalized_candidate = normalize_text(candidate)
            if normalized_candidate and normalized_candidate in normalized:
                matches.append(candidate)
        return matches

    def _matched_causes(
        self,
        normalized: str,
        terms: list[str],
        causes: list[KnowledgeCause],
    ) -> list[KnowledgeCause]:
        matches: list[KnowledgeCause] = []
        for cause in causes:
            normalized_cause = normalize_text(cause.description)
            if normalized_cause in normalized or any(term in normalized_cause for term in terms):
                matches.append(cause)
        return matches

    @staticmethod
    def _matched_terms(normalized: str, terms: list[str], candidate: str) -> list[str]:
        normalized_candidate = normalize_text(candidate)
        return [term for term in terms if term in normalized_candidate or term in normalized]

    @staticmethod
    def _flatten_terms(candidates: list[str], normalized: str) -> list[str]:
        terms: list[str] = []
        for candidate in candidates:
            normalized_candidate = normalize_text(candidate)
            terms.extend(term for term in normalized_candidate.split() if len(term) >= 2 and term in normalized)
        return terms

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value not in deduped:
                deduped.append(value)
        return deduped
