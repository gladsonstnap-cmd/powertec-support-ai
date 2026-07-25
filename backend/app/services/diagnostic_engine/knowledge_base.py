from collections.abc import Iterable

from app.services.diagnostic_engine.enums import IncidentCategory
from app.services.diagnostic_engine.knowledge_loader import KnowledgeLoader
from app.services.diagnostic_engine.knowledge_models import KnowledgeIncident, KnowledgeSearchResult
from app.services.diagnostic_engine.normalization import normalize_text


class KnowledgeBase:
    def __init__(self, incidents: Iterable[KnowledgeIncident]) -> None:
        self._incidents = tuple(sorted(incidents, key=lambda incident: incident.id))
        self._by_id = {incident.id: incident for incident in self._incidents}

    @classmethod
    def load_default(cls) -> "KnowledgeBase":
        return cls(KnowledgeLoader().load())

    def get_by_id(self, incident_id: str) -> KnowledgeIncident | None:
        return self._by_id.get(incident_id)

    def list_all(self) -> list[KnowledgeIncident]:
        return list(self._incidents)

    def find_by_category(self, category: IncidentCategory) -> list[KnowledgeIncident]:
        return [incident for incident in self._incidents if incident.category == category]

    def search(
        self,
        text: str,
        *,
        category: IncidentCategory | None = None,
        limit: int = 10,
    ) -> list[KnowledgeSearchResult]:
        normalized_query = normalize_text(text)
        terms = [term for term in normalized_query.split() if len(term) >= 2]
        if not terms or limit <= 0:
            return []

        results: list[KnowledgeSearchResult] = []
        incidents = self.find_by_category(category) if category else self._incidents

        for incident in incidents:
            score, matched_terms = self._score_incident(incident, normalized_query, terms)
            if score > 0:
                results.append(
                    KnowledgeSearchResult(
                        incident=incident,
                        score=round(score, 4),
                        matched_terms=matched_terms,
                        rationale=f"Matched {len(matched_terms)} term(s) in incident {incident.id}.",
                    )
                )

        results.sort(key=lambda result: (-result.score, result.incident.id))
        return results[:limit]

    def _score_incident(
        self,
        incident: KnowledgeIncident,
        normalized_query: str,
        terms: list[str],
    ) -> tuple[float, list[str]]:
        weighted_fields = [
            (incident.title, 0.28),
            (incident.description, 0.12),
            (" ".join(incident.symptoms), 0.24),
            (" ".join(incident.tags), 0.18),
            (" ".join(cause.description for cause in incident.possible_causes), 0.14),
            (incident.category.value, 0.08),
        ]

        matched: set[str] = set()
        score = 0.0
        for raw_value, weight in weighted_fields:
            haystack = normalize_text(raw_value)
            field_matches = {term for term in terms if term in haystack}
            if field_matches:
                matched.update(field_matches)
                score += min(weight, weight * len(field_matches) / max(len(terms), 1))
            if normalized_query and normalized_query in haystack:
                score += weight / 2

        if matched:
            score += min(0.2, len(matched) / len(terms) * 0.2)

        return min(score, 1.0), sorted(matched)
