from dataclasses import replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine.decision_engine import DecisionEngine
from app.services.diagnostic_engine.decision_models import Decision, DecisionInput, DecisionPriority, DecisionType
from app.services.diagnostic_engine.decision_policy import DecisionPolicy
from app.services.diagnostic_engine.enums import IncidentCategory, RiskLevel
from app.services.diagnostic_engine.evidence_engine import EvidenceEngine
from app.services.diagnostic_engine.hypothesis_engine import HypothesisEngine
from app.services.diagnostic_engine.knowledge_base import KnowledgeBase
from app.services.diagnostic_engine.knowledge_models import DiagnosticAction
from app.services.diagnostic_engine.models import DiagnosticContext


def _kb() -> KnowledgeBase:
    return KnowledgeBase.load_default()


def _hypothesis(message: str = "pdv nao abre", category: IncidentCategory = IncidentCategory.PDV_STARTUP):
    return HypothesisEngine(_kb()).generate(message, category, limit=1)[0]


def _decision(hypotheses, **kwargs):
    return DecisionEngine().decide(DecisionInput(hypotheses=hypotheses, **kwargs))


def _ready_hypothesis(confidence: float = 0.85):
    hypothesis = _hypothesis("produto nao aparece", IncidentCategory.PRODUCT_REGISTRATION)
    action = DiagnosticAction(
        id="safe_action",
        title="Orientar triagem segura",
        description="Registrar evidencias e orientar proximo passo sem alterar dados.",
        tool_name="support_triage_guidance",
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        requires_human=False,
    )
    return replace(
        hypothesis,
        confidence=confidence,
        missing_information=[],
        next_questions=[],
        recommended_actions=[action],
        risk_level=RiskLevel.LOW,
    )


def test_no_hypotheses_returns_insufficient_information():
    decision = _decision([])

    assert decision.decision_type == DecisionType.INSUFFICIENT_INFORMATION
    assert decision.incident_id is None


def test_low_confidence_without_question_returns_insufficient_information():
    hypothesis = replace(_ready_hypothesis(0.2), recommended_tests=[], recommended_actions=[])

    decision = _decision([hypothesis])

    assert decision.decision_type == DecisionType.INSUFFICIENT_INFORMATION


def test_asks_question_for_missing_information():
    hypothesis = _hypothesis("pdv nao abre", IncidentCategory.PDV_STARTUP)

    decision = _decision([hypothesis])

    assert decision.decision_type == DecisionType.ASK_QUESTION
    assert decision.next_question
    assert decision.confirmation_required is False


def test_asks_question_for_ambiguity():
    first = replace(_ready_hypothesis(0.58), incident_id="aaa")
    second = replace(_ready_hypothesis(0.54), incident_id="bbb")

    decision = _decision([first, second])

    assert decision.decision_type == DecisionType.ASK_QUESTION
    assert any("ambiguidade" in reason for reason in decision.reasoning)


def test_does_not_repeat_question():
    hypothesis = _hypothesis("pdv nao abre", IncidentCategory.PDV_STARTUP)
    previous = _decision([hypothesis])

    decision = _decision([hypothesis], previous_decisions=(previous,))

    assert decision.decision_type == DecisionType.ASK_QUESTION
    assert decision.next_question != previous.next_question


def test_recommends_safe_test():
    hypothesis = replace(_ready_hypothesis(0.65), recommended_actions=[])

    decision = _decision([hypothesis])

    assert decision.decision_type == DecisionType.RUN_TEST
    assert decision.recommended_test
    assert decision.recommended_action is None


def test_does_not_repeat_test():
    hypothesis = replace(_ready_hypothesis(0.65), recommended_actions=[])
    previous = _decision([hypothesis])

    decision = _decision([hypothesis], previous_decisions=(previous,))

    assert decision.decision_type == DecisionType.RUN_TEST
    assert decision.recommended_test != previous.recommended_test


def test_requests_action_confirmation():
    hypothesis = _ready_hypothesis(0.85)

    decision = _decision([hypothesis])

    assert decision.decision_type == DecisionType.REQUEST_CONFIRMATION
    assert decision.confirmation_required is True
    assert decision.recommended_action


def test_recommends_action_after_confirmation():
    hypothesis = _ready_hypothesis(0.85)

    decision = _decision([hypothesis], user_confirmation=True)

    assert decision.decision_type == DecisionType.RECOMMEND_ACTION
    assert decision.confirmation_required is False


def test_escalates_requires_human():
    hypothesis = replace(_ready_hypothesis(0.7), requires_human=True)

    decision = _decision([hypothesis])

    assert decision.decision_type == DecisionType.ESCALATE_TO_HUMAN
    assert decision.requires_human is True


def test_escalates_high_risk():
    hypothesis = replace(_ready_hypothesis(0.7), risk_level=RiskLevel.HIGH)

    decision = _decision([hypothesis])

    assert decision.decision_type == DecisionType.ESCALATE_TO_HUMAN
    assert decision.priority == DecisionPriority.HIGH


def test_escalates_critical_risk():
    hypothesis = replace(_ready_hypothesis(0.7), risk_level=RiskLevel.CRITICAL)

    decision = _decision([hypothesis])

    assert decision.decision_type == DecisionType.ESCALATE_TO_HUMAN
    assert decision.priority == DecisionPriority.CRITICAL


def test_destructive_action_is_not_recommended_automatically():
    hypothesis = _ready_hypothesis(0.86)
    action = DiagnosticAction(
        id="danger",
        title="Apagar banco de dados",
        description="Excluir dados de producao",
        tool_name="manual",
        risk_level=RiskLevel.LOW,
        requires_approval=True,
        requires_human=False,
    )
    hypothesis = replace(hypothesis, recommended_actions=[action])

    decision = _decision([hypothesis], user_confirmation=True)

    assert decision.decision_type == DecisionType.ESCALATE_TO_HUMAN


def test_sensitive_fiscal_action_is_escalated():
    hypothesis = _ready_hypothesis(0.86)
    action = DiagnosticAction(
        id="fiscal",
        title="Alterar NFCe na SEFAZ",
        description="Ajustar certificado fiscal",
        tool_name="manual",
        risk_level=RiskLevel.LOW,
        requires_approval=True,
        requires_human=False,
    )
    hypothesis = replace(hypothesis, recommended_actions=[action])

    decision = _decision([hypothesis], user_confirmation=True)

    assert decision.decision_type == DecisionType.ESCALATE_TO_HUMAN


def test_completes_with_high_confidence_and_confirmed_solution():
    hypothesis = replace(_ready_hypothesis(0.93), recommended_tests=[], recommended_actions=[])
    context = DiagnosticContext(message="ok", collected_data={"solution_confirmed": True})

    decision = _decision([hypothesis], diagnostic_context=context)

    assert decision.decision_type == DecisionType.COMPLETE
    assert decision.completion_reason


def test_does_not_complete_with_missing_information():
    hypothesis = replace(_ready_hypothesis(0.93), missing_information=["terminal afetado"])

    decision = _decision([hypothesis])

    assert decision.decision_type == DecisionType.ASK_QUESTION


def test_does_not_complete_with_relevant_contradiction():
    hypotheses = [_ready_hypothesis(0.93)]
    evidence_result = EvidenceEngine(_kb()).apply(hypotheses, "Somente um caixa esta com problema")

    decision = _decision(evidence_result.updated_hypotheses, evidence_result=evidence_result)

    assert decision.decision_type != DecisionType.COMPLETE


def test_stable_ordering_by_confidence():
    first = replace(_ready_hypothesis(0.61), incident_id="low")
    second = replace(_ready_hypothesis(0.72), incident_id="high")

    decision = _decision([first, second])

    assert decision.incident_id == "high"


def test_tie_break_by_incident_id():
    first = replace(_ready_hypothesis(0.61), incident_id="bbb")
    second = replace(_ready_hypothesis(0.61), incident_id="aaa")

    decision = _decision([first, second])

    assert decision.incident_id == "aaa"


def test_decision_confidence_is_clamped():
    hypothesis = replace(_ready_hypothesis(1.2), recommended_tests=[], recommended_actions=[])

    decision = _decision([hypothesis])

    assert 0.0 <= decision.confidence <= 1.0


def test_invalid_policy_is_rejected():
    with pytest.raises(ValueError):
        DecisionPolicy(minimum_hypothesis_confidence=0.9, test_confidence_threshold=0.5)


def test_empty_history_is_supported():
    hypothesis = _ready_hypothesis(0.85)

    decision = _decision([hypothesis], previous_decisions=())

    assert decision.reasoning


def test_limits_reached_escalates_when_confidence_insufficient():
    hypothesis = replace(_ready_hypothesis(0.5), recommended_tests=[])

    decision = _decision([hypothesis], max_questions_reached=True, max_tests_reached=True)

    assert decision.decision_type == DecisionType.ESCALATE_TO_HUMAN


def test_compatible_with_hypothesis():
    decision = _decision([_ready_hypothesis(0.65)])

    assert decision.incident_id is not None


def test_compatible_with_hypothesis_update():
    hypotheses = [_ready_hypothesis(0.7)]
    evidence_result = EvidenceEngine(_kb()).apply(hypotheses, "Nao sei")

    decision = _decision(evidence_result.hypothesis_updates, evidence_result=evidence_result)

    assert decision.incident_id == hypotheses[0].incident_id


def test_input_hypothesis_is_not_mutated():
    hypothesis = _ready_hypothesis(0.85)
    before = replace(hypothesis)

    _decision([hypothesis])

    assert hypothesis == before


def test_decision_is_repeatable():
    hypothesis = _ready_hypothesis(0.85)

    assert _decision([hypothesis]) == _decision([hypothesis])


def test_reasoning_is_filled():
    decision = _decision([_ready_hypothesis(0.85)])

    assert decision.reasoning
    assert all(reason for reason in decision.reasoning)


def test_metadata_is_deterministic_and_not_shared():
    first = _decision([_ready_hypothesis(0.85)])
    second = _decision([_ready_hypothesis(0.85)])
    first.metadata["local"] = "changed"

    assert second.metadata == {"action_id": second.metadata["action_id"]}


def test_created_files_are_utf8_without_bom():
    root = Path.cwd().parent if Path.cwd().name == "backend" else Path.cwd()
    files = [
        Path("backend/app/services/diagnostic_engine/decision_models.py"),
        Path("backend/app/services/diagnostic_engine/decision_policy.py"),
        Path("backend/app/services/diagnostic_engine/decision_engine.py"),
        Path("backend/app/services/diagnostic_engine/__init__.py"),
        Path("backend/tests/services/diagnostic_engine/test_decision_engine.py"),
    ]

    for file_path in files:
        data = (root / file_path).read_bytes()
        assert not data.startswith(b"\xef\xbb\xbf")
