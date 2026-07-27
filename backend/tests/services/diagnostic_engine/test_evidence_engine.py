from dataclasses import replace

from app.services.diagnostic_engine.enums import IncidentCategory, RiskLevel
from app.services.diagnostic_engine.evidence_engine import EvidenceEngine
from app.services.diagnostic_engine.evidence_extractor import EvidenceExtractor
from app.services.diagnostic_engine.evidence_models import Evidence, EvidencePolarity, EvidenceResult, EvidenceType
from app.services.diagnostic_engine.evidence_scoring import EvidenceScorer
from app.services.diagnostic_engine.hypothesis_engine import HypothesisEngine
from app.services.diagnostic_engine.knowledge_base import KnowledgeBase


def _hypotheses(message: str, category: IncidentCategory, limit: int = 5):
    return HypothesisEngine(KnowledgeBase.load_default()).generate(message, category, limit=limit)


def _apply(hypotheses, text: str, **kwargs) -> EvidenceResult:
    return EvidenceEngine(KnowledgeBase.load_default()).apply(hypotheses, text, **kwargs)


def _update_for(result: EvidenceResult, incident_id: str):
    return next(update for update in result.hypothesis_updates if update.incident_id == incident_id)


def test_creates_evidence_model_from_user_answer():
    evidence = EvidenceExtractor().extract("O PostgreSQL esta parado.")

    assert isinstance(evidence, Evidence)
    assert evidence.evidence_type == EvidenceType.USER_ANSWER
    assert evidence.source == EvidenceType.USER_ANSWER
    assert evidence.normalized_text == "o postgresql esta parado."
    assert evidence.polarity == EvidencePolarity.SUPPORTING
    assert "database_service_stopped" in evidence.related_incident_ids


def test_extracts_supporting_evidence_without_accents():
    evidence = EvidenceExtractor().extract("A SEFAZ está indisponível")

    assert evidence.normalized_text == "a sefaz esta indisponivel"
    assert evidence.polarity == EvidencePolarity.SUPPORTING
    assert evidence.field_name == "sefaz_status"


def test_extracts_contradicting_evidence():
    evidence = EvidenceExtractor().extract("O PostgreSQL esta iniciado")

    assert evidence.polarity == EvidencePolarity.CONTRADICTING
    assert evidence.confidence_delta < 0
    assert evidence.field_value == "running"


def test_extracts_neutral_evidence():
    evidence = EvidenceExtractor().extract("Nao sei")

    assert evidence.polarity == EvidencePolarity.NEUTRAL
    assert evidence.confidence_delta == 0.0
    assert evidence.matched_terms == []


def test_detects_negative_operational_phrase_as_contradicting():
    evidence = EvidenceExtractor().extract("O servidor responde ao ping")

    assert evidence.polarity == EvidencePolarity.CONTRADICTING
    assert evidence.field_name == "server_ping"


def test_supporting_score_is_positive_for_related_hypothesis():
    hypothesis = _hypotheses("banco nao conecta postgres", IncidentCategory.DATABASE, limit=1)[0]
    evidence = EvidenceExtractor().extract("O PostgreSQL esta parado")

    delta, reasoning = EvidenceScorer().score(hypothesis, evidence)

    assert delta > 0
    assert reasoning


def test_contradicting_score_is_negative_for_related_hypothesis():
    hypothesis = _hypotheses("banco nao conecta postgres", IncidentCategory.DATABASE, limit=1)[0]
    evidence = EvidenceExtractor().extract("O PostgreSQL esta iniciado")

    delta, reasoning = EvidenceScorer().score(hypothesis, evidence)

    assert delta < 0
    assert any("contraria" in reason for reason in reasoning)


def test_neutral_score_is_zero():
    hypothesis = _hypotheses("banco nao conecta postgres", IncidentCategory.DATABASE, limit=1)[0]
    evidence = EvidenceExtractor().extract("Vou verificar")

    delta, _ = EvidenceScorer().score(hypothesis, evidence)

    assert delta == 0.0


def test_database_stopped_evidence_increases_database_service_stopped():
    hypotheses = _hypotheses("postgres parado banco", IncidentCategory.DATABASE, limit=5)
    result = _apply(hypotheses, "O PostgreSQL esta parado")
    update = _update_for(result, "database_service_stopped")

    assert update.confidence_delta > 0
    assert update.new_confidence > update.previous_confidence
    assert result.updated_hypotheses[0].incident_id == "database_service_stopped"


def test_database_started_evidence_reduces_database_service_stopped():
    hypotheses = _hypotheses("postgres parado banco", IncidentCategory.DATABASE, limit=5)
    result = _apply(hypotheses, "O PostgreSQL esta iniciado")
    update = _update_for(result, "database_service_stopped")

    assert update.confidence_delta < 0
    assert update.new_confidence < update.previous_confidence
    assert 0.0 <= update.new_confidence <= 1.0


def test_server_without_ping_favors_server_offline():
    hypotheses = _hypotheses("servidor offline todos os caixas", IncidentCategory.SERVER, limit=5)
    result = _apply(hypotheses, "Servidor sem ping")

    assert _update_for(result, "server_offline").confidence_delta > 0


def test_server_ping_response_reduces_server_offline():
    hypotheses = _hypotheses("servidor offline todos os caixas", IncidentCategory.SERVER, limit=5)
    result = _apply(hypotheses, "Servidor responde ao ping")

    assert _update_for(result, "server_offline").confidence_delta < 0


def test_all_cashiers_failure_favors_server_or_network_incidents():
    hypotheses = _hypotheses("sem acesso", IncidentCategory.NETWORK, limit=8)
    result = _apply(hypotheses, "Todos os caixas estao sem acesso")
    positive = [update.incident_id for update in result.hypothesis_updates if update.confidence_delta > 0]

    assert "server_offline" in positive or "all_terminals_cannot_reach_server" in positive


def test_single_cashier_failure_reduces_global_incidents():
    hypotheses = _hypotheses("todos os caixas sem rede", IncidentCategory.NETWORK, limit=8)
    result = _apply(hypotheses, "Somente um caixa esta com problema")

    assert _update_for(result, "all_terminals_cannot_reach_server").confidence_delta < 0


def test_printer_test_page_reduces_printer_failure():
    hypotheses = _hypotheses("impressora nao imprime", IncidentCategory.PRINTER, limit=5)
    result = _apply(hypotheses, "A impressora imprime pagina de teste")

    assert _update_for(result, "receipt_printer_not_printing").confidence_delta < 0


def test_sefaz_unavailable_favors_fiscal_external_incident():
    hypotheses = _hypotheses("sefaz fora do ar", IncidentCategory.FISCAL, limit=5)
    result = _apply(hypotheses, "A SEFAZ esta indisponivel")

    assert _update_for(result, "sefaz_unavailable").confidence_delta > 0


def test_pinpad_offline_favors_tef_hypothesis():
    hypotheses = _hypotheses("pinpad offline", IncidentCategory.TEF, limit=5)
    result = _apply(hypotheses, "O pinpad nao liga")

    assert _update_for(result, "pinpad_offline").confidence_delta > 0


def test_neutral_answer_does_not_change_confidence():
    hypotheses = _hypotheses("servidor offline", IncidentCategory.SERVER, limit=3)
    result = _apply(hypotheses, "Nao sei")

    assert all(update.confidence_delta == 0.0 for update in result.hypothesis_updates)
    assert [h.confidence for h in result.updated_hypotheses] == [h.confidence for h in hypotheses]


def test_same_evidence_is_not_applied_twice():
    hypotheses = _hypotheses("postgres parado banco", IncidentCategory.DATABASE, limit=5)
    first = _apply(hypotheses, "O PostgreSQL esta parado")
    second = _apply(first.updated_hypotheses, "O PostgreSQL esta parado", evidence_history=first.evidence_history)

    assert len(second.evidence_history) == len(first.evidence_history)
    assert all(update.confidence_delta == 0.0 for update in second.hypothesis_updates)


def test_one_evidence_can_update_multiple_hypotheses():
    hypotheses = _hypotheses("todos os caixas sem rede servidor", IncidentCategory.NETWORK, limit=8)
    result = _apply(hypotheses, "Todos os caixas estao sem acesso")

    assert sum(1 for update in result.hypothesis_updates if update.confidence_delta > 0) >= 2


def test_ranking_can_change_after_evidence():
    hypotheses = _hypotheses("servidor banco", IncidentCategory.SERVER, limit=8)
    result = _apply(hypotheses, "O PostgreSQL esta parado")

    assert any(update.rank_before != update.rank_after for update in result.hypothesis_updates)
    assert result.updated_hypotheses == sorted(result.updated_hypotheses, key=lambda h: (-h.confidence, h.incident_id))


def test_missing_information_is_updated_from_evidence_field():
    hypothesis = _hypotheses("postgres parado banco", IncidentCategory.DATABASE, limit=1)[0]
    incident = replace(hypothesis.incident, required_information=["database_service_status", "terminal afetado"])
    hypothesis = replace(hypothesis, incident=incident, missing_information=["database_service_status", "terminal afetado"])

    result = _apply([hypothesis], "O PostgreSQL esta parado")

    assert "database_service_status" not in result.updated_hypotheses[0].missing_information
    assert result.known_information["database_service_status"] == "stopped"


def test_next_question_does_not_repeat_previous_question():
    hypotheses = _hypotheses("pdv nao abre", IncidentCategory.PDV_STARTUP, limit=1)
    previous_question_id = hypotheses[0].next_questions[0].id

    result = _apply(hypotheses, "Somente um caixa esta com problema", asked_question_ids={previous_question_id})

    assert result.updated_hypotheses[0].next_questions[0].id != previous_question_id


def test_contradicting_evidence_never_moves_confidence_outside_limits():
    hypothesis = _hypotheses("servidor offline", IncidentCategory.SERVER, limit=1)[0]
    hypothesis = replace(hypothesis, confidence=0.02)

    result = _apply([hypothesis], "Servidor responde ao ping")

    assert 0.0 <= result.updated_hypotheses[0].confidence <= 1.0


def test_history_preserves_previous_evidence():
    hypotheses = _hypotheses("servidor offline", IncidentCategory.SERVER, limit=3)
    first = _apply(hypotheses, "Servidor sem ping")
    second = _apply(first.updated_hypotheses, "Todos os caixas estao sem acesso", evidence_history=first.evidence_history)

    assert len(second.evidence_history) == 2
    assert second.evidence_history[0] == first.evidence


def test_requires_human_and_risk_level_are_preserved():
    hypothesis = _hypotheses("banco corrompido", IncidentCategory.DATABASE, limit=1)[0]
    result = _apply([hypothesis], "O PostgreSQL esta parado")

    assert result.updated_hypotheses[0].requires_human == hypothesis.requires_human
    assert result.updated_hypotheses[0].risk_level == hypothesis.risk_level


def test_processing_is_stable_and_deterministic():
    hypotheses = _hypotheses("sefaz fora do ar", IncidentCategory.FISCAL, limit=5)

    first = _apply(hypotheses, "A SEFAZ esta indisponivel")
    second = _apply(hypotheses, "A SEFAZ esta indisponivel")

    assert first == second


def test_deterministic_tie_break_after_evidence():
    hypothesis = _hypotheses("impressora nao imprime", IncidentCategory.PRINTER, limit=1)[0]
    first = replace(hypothesis, incident_id="aaa_printer", confidence=0.5)
    second = replace(hypothesis, incident_id="zzz_printer", confidence=0.5)

    result = _apply([second, first], "Nao sei")

    assert [item.incident_id for item in result.updated_hypotheses] == ["aaa_printer", "zzz_printer"]


def test_idempotent_reprocessing_keeps_rank_and_confidence():
    hypotheses = _hypotheses("pinpad offline", IncidentCategory.TEF, limit=5)
    first = _apply(hypotheses, "Pinpad offline")
    second = _apply(first.updated_hypotheses, "Pinpad offline", evidence_history=first.evidence_history)

    assert [(h.incident_id, h.confidence) for h in first.updated_hypotheses] == [
        (h.incident_id, h.confidence) for h in second.updated_hypotheses
    ]
