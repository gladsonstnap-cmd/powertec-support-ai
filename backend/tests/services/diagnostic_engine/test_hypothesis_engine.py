from dataclasses import replace

from app.services.diagnostic_engine.enums import IncidentCategory, RiskLevel
from app.services.diagnostic_engine.hypothesis_engine import HypothesisEngine
from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.knowledge_base import KnowledgeBase
from app.services.diagnostic_engine.knowledge_models import DiagnosticQuestion
from app.services.diagnostic_engine.question_selector import QuestionSelector
from app.services.diagnostic_engine.scoring import HypothesisScorer


def _engine() -> HypothesisEngine:
    return HypothesisEngine(KnowledgeBase.load_default())


def test_generates_single_hypothesis_with_limit_one():
    hypotheses = _engine().generate("o pdv nao abre no caixa 2", IncidentCategory.PDV_STARTUP, limit=1)

    assert len(hypotheses) == 1
    assert hypotheses[0].incident.category == IncidentCategory.PDV_STARTUP
    assert hypotheses[0].incident_id == hypotheses[0].incident.id
    assert 0.0 <= hypotheses[0].confidence <= 1.0


def test_generates_multiple_hypotheses_ordered_by_confidence():
    hypotheses = _engine().generate("postgres com timeout no banco", IncidentCategory.DATABASE, limit=4)

    assert len(hypotheses) >= 2
    assert hypotheses == sorted(hypotheses, key=lambda hypothesis: (-hypothesis.confidence, hypothesis.incident_id))
    assert hypotheses[0].incident.category == IncidentCategory.DATABASE


def test_score_is_clamped_between_zero_and_one():
    scorer = HypothesisScorer()
    incident = KnowledgeBase.load_default().get_by_id("database_connection_refused")

    score = scorer.score(
        "postgres postgresql banco connection refused banco nao conecta timeout base de dados",
        incident,
        IncidentCategory.DATABASE,
    )

    assert 0.0 <= score.confidence <= 1.0


def test_deterministic_tie_break_uses_incident_id():
    kb = KnowledgeBase.load_default()
    base = kb.get_by_id("receipt_printer_not_printing")
    first = replace(base, id="aaa_equal_printer")
    second = replace(base, id="zzz_equal_printer")
    engine = HypothesisEngine(KnowledgeBase([second, first]))

    hypotheses = engine.generate("impressora nao imprime", IncidentCategory.PRINTER, limit=2)

    assert [hypothesis.incident_id for hypothesis in hypotheses] == ["aaa_equal_printer", "zzz_equal_printer"]


def test_empty_knowledge_base_returns_no_hypotheses():
    engine = HypothesisEngine(KnowledgeBase([]))

    assert engine.generate("pdv nao abre", IncidentCategory.PDV_STARTUP) == []


def test_partial_message_nao_abre_favors_startup():
    hypothesis = _engine().generate("nao abre", IncidentCategory.UNKNOWN, limit=1)[0]

    assert hypothesis.incident.category == IncidentCategory.PDV_STARTUP


def test_accented_update_message_favors_update():
    hypothesis = _engine().generate("erro depois da atualização", IncidentCategory.UPDATE, limit=1)[0]

    assert hypothesis.incident.category == IncidentCategory.UPDATE
    assert "atualizacao" in hypothesis.matched_terms or "atualizacao" in " ".join(hypothesis.reasoning)


def test_all_cashiers_message_favors_server():
    hypothesis = _engine().generate("todos os caixas parados", IncidentCategory.SERVER, limit=1)[0]

    assert hypothesis.incident.category == IncidentCategory.SERVER


def test_postgres_message_favors_database():
    hypothesis = _engine().generate("postgres parado no servidor", IncidentCategory.DATABASE, limit=1)[0]

    assert hypothesis.incident.category == IncidentCategory.DATABASE


def test_printer_sefaz_and_pinpad_terms_favor_expected_categories():
    engine = _engine()

    assert engine.generate("impressora nao imprime", IncidentCategory.PRINTER, limit=1)[0].incident.category == IncidentCategory.PRINTER
    assert engine.generate("sefaz fora do ar", IncidentCategory.FISCAL, limit=1)[0].incident.category == IncidentCategory.FISCAL
    assert engine.generate("pinpad offline", IncidentCategory.TEF, limit=1)[0].incident.category == IncidentCategory.TEF


def test_hypothesis_contains_reasoning_matches_and_operational_recommendations():
    hypothesis = _engine().generate("banco nao conecta postgres", IncidentCategory.DATABASE, limit=1)[0]

    assert isinstance(hypothesis, Hypothesis)
    assert hypothesis.reasoning
    assert any("categoria DATABASE" in reason for reason in hypothesis.reasoning)
    assert hypothesis.matched_terms
    assert hypothesis.matched_symptoms or hypothesis.matched_tags or hypothesis.matched_causes
    assert hypothesis.supporting_evidence
    assert hypothesis.recommended_tests
    assert hypothesis.recommended_actions
    assert len(hypothesis.next_questions) <= 1


def test_question_selector_prefers_required_priority_and_unknown_information():
    incident = KnowledgeBase.load_default().get_by_id("pdv_application_not_starting")
    selector = QuestionSelector()

    selected = selector.select_next_question(incident)

    assert selected.id.endswith("_q_scope")


def test_question_selector_does_not_repeat_or_ask_known_fields():
    incident = KnowledgeBase.load_default().get_by_id("pdv_application_not_starting")
    selector = QuestionSelector()

    selected = selector.select_next_question(
        incident,
        known_information={"affected_scope": "um terminal"},
        asked_question_ids={"pdv_application_not_starting_q_scope"},
    )

    assert selected.id.endswith("_q_start_time")


def test_question_selector_returns_none_when_all_questions_known_or_asked():
    incident = KnowledgeBase.load_default().get_by_id("pdv_application_not_starting")
    asked = {question.id for question in incident.questions}

    assert QuestionSelector().select_next_question(incident, asked_question_ids=asked) is None


def test_requires_human_and_risk_level_propagate_from_knowledge_base():
    hypothesis = _engine().generate("banco corrompido com erro de integridade", IncidentCategory.DATABASE, limit=1)[0]

    assert hypothesis.requires_human is True
    assert hypothesis.risk_level == RiskLevel.HIGH


def test_generation_is_stable_and_deterministic():
    engine = _engine()

    first = engine.generate("sefaz fora do ar nfce", IncidentCategory.FISCAL, limit=5)
    second = engine.generate("sefaz fora do ar nfce", IncidentCategory.FISCAL, limit=5)

    assert first == second


def test_next_questions_contains_only_one_question():
    hypothesis = _engine().generate("produto nao aparece", IncidentCategory.PRODUCT_REGISTRATION, limit=1)[0]

    assert len(hypothesis.next_questions) <= 1
    assert all(isinstance(question, DiagnosticQuestion) for question in hypothesis.next_questions)


def test_known_information_reduces_missing_information():
    hypothesis = _engine().generate(
        "pdv nao abre",
        IncidentCategory.PDV_STARTUP,
        limit=1,
        known_information={"terminal afetado": "terminal afetado"},
    )[0]

    assert "terminal afetado" not in hypothesis.missing_information
