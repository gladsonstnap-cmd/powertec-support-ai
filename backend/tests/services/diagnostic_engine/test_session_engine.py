from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.diagnostic_engine import (
    DiagnosticSession,
    DiagnosticSessionEngine,
    DiagnosticSessionPolicy,
    DiagnosticSessionStatus,
)
from app.services.diagnostic_engine.decision_models import Decision, DecisionPriority, DecisionType
from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.evidence_models import Evidence, EvidenceResult
from app.services.diagnostic_engine.workflow_engine import DiagnosticWorkflowEngine
from app.services.diagnostic_engine.workflow_models import WorkflowResult


def decision(kind, *, question=None, test=None, action=None, completion=None):
    return Decision(
        decision_type=kind,
        priority=DecisionPriority.NORMAL,
        title="Decisão",
        message="Mensagem objetiva.",
        reasoning=("regra determinística",),
        confidence=0.75,
        incident_id="incident-1",
        requires_human=kind == DecisionType.ESCALATE_TO_HUMAN,
        risk_level=RiskLevel.LOW,
        next_question=question,
        recommended_test=test,
        recommended_action=action,
        confirmation_required=kind == DecisionType.REQUEST_CONFIRMATION,
        completion_reason=completion,
    )


def workflow_result(kind=DecisionType.ASK_QUESTION, *, question="Qual terminal foi afetado?", evidence_text="resposta"):
    evidence = Evidence.neutral(evidence_text)
    evidence_result = EvidenceResult(
        evidence=evidence,
        updated_hypotheses=[SimpleNamespace(incident_id="hypothesis-1", confidence=0.5)],
        hypothesis_updates=[],
        selected_question=None,
        known_information={"terminal": "caixa 1"},
        unresolved_information=["erro exibido"],
        evidence_history=[evidence],
    )
    kwargs = {}
    if kind == DecisionType.ASK_QUESTION:
        kwargs["question"] = question
    elif kind == DecisionType.RUN_TEST:
        kwargs["test"] = "Verificar conexão"
    elif kind in {DecisionType.REQUEST_CONFIRMATION, DecisionType.RECOMMEND_ACTION}:
        kwargs["action"] = "Reiniciar serviço"
    elif kind == DecisionType.COMPLETE:
        kwargs["completion"] = "solução confirmada"
    return WorkflowResult(
        intent=SimpleNamespace(intent="INCIDENT"),
        incident=SimpleNamespace(category="NETWORK"),
        knowledge_result=[SimpleNamespace(score=1.0)],
        hypotheses=list(evidence_result.updated_hypotheses),
        evidence_result=evidence_result,
        decision=decision(kind, **kwargs),
        success=True,
    )


class FakeWorkflow:
    def __init__(self, *results):
        self.results = list(results or (workflow_result(),))
        self.calls = []

    def run(self, message, **kwargs):
        self.calls.append((message, kwargs))
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


def engine(*results, policy=None):
    workflow = FakeWorkflow(*results)
    return DiagnosticSessionEngine(workflow, policy), workflow


def test_start_session():
    subject, _ = engine()
    turn = subject.start_session("Sistema não abre", session_id="session-1")
    assert turn.session.session_id == "session-1"
    assert turn.session.interaction_count == 1
    assert turn.workflow_result is not None


def test_continue_session():
    subject, workflow = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    first = subject.start_session("Sistema não abre", session_id="session-1")
    second = subject.continue_session(first.session, "Somente o caixa 1")
    assert second.current_status == DiagnosticSessionStatus.READY_FOR_TEST
    assert len(workflow.calls) == 2


def test_continue_preserves_current_intent_and_incident():
    first_result = workflow_result()
    second_result = workflow_result(DecisionType.RUN_TEST)
    second_result.intent = SimpleNamespace(intent="INFORMATION")
    second_result.incident = SimpleNamespace(category="UNKNOWN")
    subject, _ = engine(first_result, second_result)
    first = subject.start_session("Sistema não abre").session
    second = subject.continue_session(first, "somente o caixa 1").session
    assert second.intent == first.intent
    assert second.incident == first.incident


def test_provided_session_id_is_preserved():
    subject, _ = engine()
    assert subject.start_session("erro", session_id="known-id").session.session_id == "known-id"


def test_generated_session_id_is_uuid():
    subject, _ = engine()
    generated = subject.start_session("erro").session.session_id
    assert str(UUID(generated)) == generated


def test_new_status_does_not_remain_after_start():
    subject, _ = engine()
    assert subject.start_session("erro").session.status != DiagnosticSessionStatus.NEW


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (DecisionType.ASK_QUESTION, DiagnosticSessionStatus.WAITING_USER),
        (DecisionType.RUN_TEST, DiagnosticSessionStatus.READY_FOR_TEST),
        (DecisionType.REQUEST_CONFIRMATION, DiagnosticSessionStatus.WAITING_CONFIRMATION),
        (DecisionType.RECOMMEND_ACTION, DiagnosticSessionStatus.READY_FOR_ACTION),
        (DecisionType.ESCALATE_TO_HUMAN, DiagnosticSessionStatus.ESCALATED),
        (DecisionType.COMPLETE, DiagnosticSessionStatus.COMPLETED),
    ],
)
def test_decision_maps_to_status(kind, expected):
    subject, _ = engine(workflow_result(kind))
    assert subject.start_session("erro").session.status == expected


@pytest.mark.parametrize("command", ["cancelar", "encerrar"])
def test_cancel_commands(command):
    subject, _ = engine()
    session = subject.start_session("erro").session
    turn = subject.continue_session(session, command)
    assert turn.session.status == DiagnosticSessionStatus.CANCELLED


def test_cancel_session_method():
    subject, _ = engine()
    session = subject.start_session("erro").session
    turn = subject.cancel_session(session, "solicitado")
    assert turn.session.metadata["terminal_reason"] == "solicitado"


@pytest.mark.parametrize("command", ["reiniciar", "começar novamente"])
def test_restart_commands(command):
    subject, workflow = engine()
    session = subject.start_session("erro original", session_id="same-id").session
    turn = subject.continue_session(session, command)
    assert turn.session.session_id == "same-id"
    assert turn.session.original_message == "erro original"
    assert turn.session.interaction_count == 1
    assert len(workflow.calls) == 2


def test_status_command_does_not_run_workflow_or_change_state():
    subject, workflow = engine()
    session = subject.start_session("erro").session
    turn = subject.continue_session(session, "status")
    assert len(workflow.calls) == 1
    assert turn.session is session
    assert turn.state_changed is False


@pytest.mark.parametrize("command", ["atendente", "humano"])
def test_human_commands_escalate(command):
    subject, _ = engine()
    session = subject.start_session("erro").session
    assert subject.continue_session(session, command).session.status == DiagnosticSessionStatus.ESCALATED


def test_hypotheses_are_preserved_and_forwarded():
    subject, workflow = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    session = subject.start_session("erro").session
    subject.continue_session(session, "resposta nova")
    assert workflow.calls[1][1]["previous_hypotheses"] == session.hypotheses


def test_evidence_is_preserved_and_forwarded():
    subject, workflow = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    session = subject.start_session("erro").session
    subject.continue_session(session, "resposta nova")
    assert workflow.calls[1][1]["previous_evidence"] == session.evidence_history


def test_decisions_are_preserved_and_appended():
    subject, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    session = subject.start_session("erro").session
    continued = subject.continue_session(session, "resposta nova").session
    assert continued.decisions[0] == session.decisions[0]
    assert len(continued.decisions) == 2


def test_previous_question_is_preserved():
    subject, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    session = subject.start_session("erro").session
    continued = subject.continue_session(session, "resposta nova").session
    assert session.current_question in continued.questions_asked


def test_answer_is_added():
    subject, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    session = subject.start_session("erro").session
    continued = subject.continue_session(session, "Caixa 2").session
    assert continued.answers == ("Caixa 2",)


def test_interaction_count_increments():
    subject, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    session = subject.start_session("erro").session
    assert subject.continue_session(session, "resposta").session.interaction_count == 2


def test_previous_session_is_not_mutated():
    subject, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    session = subject.start_session("erro").session
    snapshot = deepcopy(session)
    subject.continue_session(session, "resposta")
    assert session == snapshot


@pytest.mark.parametrize("status", [DiagnosticSessionStatus.CANCELLED, DiagnosticSessionStatus.FAILED])
def test_blocked_session_cannot_continue(status):
    subject, workflow = engine()
    session = subject.start_session("erro").session
    blocked = DiagnosticSession(**{**session.__dict__, "status": status})
    turn = subject.continue_session(blocked, "nova resposta")
    assert turn.state_changed is False
    assert len(workflow.calls) == 1


def test_completed_session_respects_policy():
    subject, workflow = engine(workflow_result(DecisionType.COMPLETE))
    session = subject.start_session("erro").session
    assert subject.continue_session(session, "nova resposta").state_changed is False
    assert len(workflow.calls) == 1


def test_interaction_limit_escalates():
    policy = DiagnosticSessionPolicy(max_interactions=1, max_questions=1, max_tests=1)
    subject, workflow = engine(policy=policy)
    session = subject.start_session("erro").session
    turn = subject.continue_session(session, "resposta")
    assert turn.session.status == DiagnosticSessionStatus.ESCALATED
    assert "limite" in turn.session.metadata["terminal_reason"]
    assert len(workflow.calls) == 1


def test_repeated_question_is_not_returned_again():
    repeated = "Qual terminal foi afetado?"
    subject, _ = engine(workflow_result(question=repeated), workflow_result(question=repeated))
    session = subject.start_session("erro").session
    turn = subject.continue_session(session, "caixa 1")
    assert turn.session.status == DiagnosticSessionStatus.ESCALATED
    assert turn.session.current_question is None


def test_duplicate_evidence_is_not_added():
    same_first = workflow_result(evidence_text="igual")
    same_second = workflow_result(DecisionType.RUN_TEST, evidence_text="igual")
    subject, _ = engine(same_first, same_second)
    session = subject.start_session("erro").session
    continued = subject.continue_session(session, "resposta").session
    assert len(continued.evidence_history) == 1


@pytest.mark.parametrize("confirmation", [True, False, None])
def test_user_confirmation_is_forwarded(confirmation):
    subject, workflow = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    session = subject.start_session("erro").session
    continued = subject.continue_session(session, "resposta", user_confirmation=confirmation).session
    assert workflow.calls[1][1]["user_confirmation"] is confirmation
    assert continued.user_confirmation is confirmation


@pytest.mark.parametrize("message", ["", "   ", None])
def test_empty_message_is_rejected(message):
    subject, _ = engine()
    with pytest.raises(ValueError, match="message"):
        subject.start_session(message)


def test_command_normalization_removes_accents_and_case():
    subject, _ = engine()
    session = subject.start_session("erro").session
    turn = subject.continue_session(session, "COMEÇAR NOVAMENTE")
    assert turn.session.interaction_count == 1


def test_deterministic_session_with_supplied_id(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.session_engine.time.monotonic", lambda: 10.0)
    first_engine, _ = engine()
    second_engine, _ = engine()
    first = first_engine.start_session("erro", session_id="fixed").session
    second = second_engine.start_session("erro", session_id="fixed").session
    assert first == second


def test_dependency_injection():
    workflow = FakeWorkflow()
    policy = DiagnosticSessionPolicy()
    subject = DiagnosticSessionEngine(workflow, policy)
    assert subject.workflow_engine is workflow
    assert subject.policy is policy


def test_default_constructor():
    subject = DiagnosticSessionEngine()
    assert isinstance(subject.workflow_engine, DiagnosticWorkflowEngine)
    assert isinstance(subject.policy, DiagnosticSessionPolicy)


def test_workflow_error_becomes_failed_session():
    failed = WorkflowResult(success=False, errors=["INTENT: falha"])
    subject, _ = engine(failed)
    turn = subject.start_session("erro")
    assert turn.session.status == DiagnosticSessionStatus.FAILED
    assert turn.session.errors == ("INTENT: falha",)


@pytest.mark.parametrize(
    ("kind", "fragment"),
    [
        (DecisionType.ASK_QUESTION, "terminal"),
        (DecisionType.RUN_TEST, "Realize o teste recomendado"),
        (DecisionType.REQUEST_CONFIRMATION, "Mensagem objetiva"),
        (DecisionType.RECOMMEND_ACTION, "Ação recomendada"),
        (DecisionType.ESCALATE_TO_HUMAN, "atendimento técnico humano"),
        (DecisionType.COMPLETE, "Diagnóstico concluído"),
        (DecisionType.INSUFFICIENT_INFORMATION, "informações suficientes"),
    ],
)
def test_response_is_objective(kind, fragment):
    subject, _ = engine(workflow_result(kind))
    assert fragment in subject.start_session("erro").response_message


def test_metadata_is_deterministic(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.session_engine.time.monotonic", lambda: 1.0)
    subject, _ = engine()
    first = subject.start_session("erro", session_id="id").session.metadata
    second = subject.start_session("erro", session_id="id").session.metadata
    assert first == second == {"session_id_generated": False}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_interactions": 0},
        {"max_questions": -1},
        {"max_tests": -1},
        {"max_repeated_answers": -1},
        {"max_interactions": 2, "max_questions": 3},
    ],
)
def test_policy_rejects_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        DiagnosticSessionPolicy(**kwargs)


def test_session_collections_are_defensive_copies():
    answers = ["a"]
    metadata = {"nested": {"value": 1}}
    session = DiagnosticSession(
        session_id="id",
        status=DiagnosticSessionStatus.NEW,
        original_message="erro",
        last_message="erro",
        answers=answers,
        metadata=metadata,
    )
    answers.append("b")
    metadata["nested"]["value"] = 2
    assert session.answers == ("a",)
    assert session.metadata == {"nested": {"value": 1}}


def test_files_are_utf8_without_bom():
    paths = [
        "app/services/diagnostic_engine/session_models.py",
        "app/services/diagnostic_engine/session_policy.py",
        "app/services/diagnostic_engine/session_engine.py",
        "app/services/diagnostic_engine/workflow_engine.py",
        "app/services/diagnostic_engine/__init__.py",
        "tests/services/diagnostic_engine/test_session_engine.py",
    ]
    for path in paths:
        content = Path(path).read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
