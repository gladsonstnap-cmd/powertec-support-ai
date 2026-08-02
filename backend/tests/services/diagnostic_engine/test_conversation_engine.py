from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.diagnostic_engine import (
    ConversationCommand,
    ConversationInput,
    ConversationResponse,
    DiagnosticConversationEngine,
    DiagnosticSession,
    DiagnosticSessionEngine,
    DiagnosticSessionStatus,
)
from app.services.diagnostic_engine.conversation_engine import HELP_MESSAGE
from app.services.diagnostic_engine.decision_models import Decision, DecisionPriority, DecisionType
from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.models import DiagnosticContext
from app.services.diagnostic_engine.session_models import SessionTurnResult
from app.services.diagnostic_engine.workflow_models import WorkflowResult


def make_decision(kind=DecisionType.ASK_QUESTION, question="Qual terminal foi afetado?"):
    return Decision(
        decision_type=kind,
        priority=DecisionPriority.NORMAL,
        title="Decisão",
        message="Resposta objetiva.",
        reasoning=("regra",),
        confidence=0.75,
        incident_id="incident-1",
        requires_human=kind == DecisionType.ESCALATE_TO_HUMAN,
        risk_level=RiskLevel.LOW,
        next_question=question if kind == DecisionType.ASK_QUESTION else None,
        recommended_test="Verificar conexão" if kind == DecisionType.RUN_TEST else None,
        recommended_action="Reiniciar serviço" if kind == DecisionType.RECOMMEND_ACTION else None,
        confirmation_required=kind == DecisionType.REQUEST_CONFIRMATION,
        completion_reason="confirmado" if kind == DecisionType.COMPLETE else None,
    )


def make_session(
    status=DiagnosticSessionStatus.WAITING_USER,
    *,
    session_id="session-1",
    metadata=None,
    interaction_count=1,
    question="Qual terminal foi afetado?",
):
    decision = make_decision()
    return DiagnosticSession(
        session_id=session_id,
        status=status,
        original_message="Sistema não abre",
        last_message="Sistema não abre",
        hypotheses=(SimpleNamespace(incident_id="hypothesis-1", confidence=0.75),),
        decisions=(decision,),
        current_question=question,
        created_at_monotonic=1.0,
        updated_at_monotonic=1.0,
        interaction_count=interaction_count,
        metadata=metadata or {"origin": "test"},
    )


def make_turn(session=None, *, response="Qual terminal foi afetado?", workflow=True, changed=True):
    session = session or make_session()
    result = WorkflowResult(decision=session.decisions[-1], success=True) if workflow else None
    return SessionTurnResult(
        session=session,
        workflow_result=result,
        response_message=response,
        next_expected_input=session.current_question,
        state_changed=changed,
        previous_status=DiagnosticSessionStatus.NEW,
        current_status=session.status,
    )


class FakeSessionEngine:
    def __init__(self):
        self.calls = []
        self.counter = 0
        self.raise_error = None

    def start_session(self, message, session_id=None, context=None):
        self.calls.append(("start", message, session_id, context))
        if self.raise_error:
            raise self.raise_error
        self.counter += 1
        session = make_session(session_id=f"new-{self.counter}", metadata={"generated": True})
        return make_turn(session)

    def continue_session(self, session, message, context=None, user_confirmation=None):
        self.calls.append(("continue", session, message, context))
        if self.raise_error:
            raise self.raise_error
        if message in {"humano", "atendente"}:
            updated = replace(session, status=DiagnosticSessionStatus.ESCALATED, current_question=None)
            return make_turn(updated, response="Este caso precisa de atendimento técnico humano.", workflow=False)
        updated = replace(session, interaction_count=session.interaction_count + 1, last_message=message)
        return make_turn(updated)

    def cancel_session(self, session, reason=None):
        self.calls.append(("cancel", session, reason))
        if self.raise_error:
            raise self.raise_error
        updated = replace(session, status=DiagnosticSessionStatus.CANCELLED, current_question=None)
        return make_turn(updated, response="Sessão cancelada.", workflow=False)


def subject():
    dependency = FakeSessionEngine()
    return DiagnosticConversationEngine(dependency), dependency


def test_new_conversation_starts_session():
    engine, dependency = subject()
    response = engine.start_conversation("Sistema não abre")
    assert dependency.calls[0][0] == "start"
    assert response.session is not None


def test_existing_conversation_continues_session():
    engine, dependency = subject()
    session = make_session()
    response = engine.continue_conversation(session, "Somente o caixa 2")
    assert dependency.calls[0][0] == "continue"
    assert response.session.interaction_count == 2


def test_process_without_session_starts():
    engine, dependency = subject()
    engine.process(ConversationInput("erro"))
    assert dependency.calls[0][0] == "start"


def test_process_with_session_continues():
    engine, dependency = subject()
    engine.process(ConversationInput("resposta", make_session()))
    assert dependency.calls[0][0] == "continue"


def test_context_is_forwarded_on_start():
    engine, dependency = subject()
    context = DiagnosticContext(message="erro")
    engine.start_conversation("erro", context)
    assert dependency.calls[0][3] is context


def test_context_is_forwarded_on_continue():
    engine, dependency = subject()
    context = DiagnosticContext(message="resposta")
    engine.continue_conversation(make_session(), "resposta", context)
    assert dependency.calls[0][3] is context


@pytest.mark.parametrize(
    ("message", "command"),
    [
        ("status", ConversationCommand.STATUS),
        ("cancelar", ConversationCommand.CANCEL),
        ("encerrar", ConversationCommand.CANCEL),
        ("reiniciar", ConversationCommand.RESTART),
        ("começar novamente", ConversationCommand.RESTART),
        ("humano", ConversationCommand.ESCALATE),
        ("atendente", ConversationCommand.ESCALATE),
        ("ajuda", ConversationCommand.HELP),
        ("help", ConversationCommand.HELP),
        ("problema no caixa", ConversationCommand.NORMAL),
    ],
)
def test_command_recognition(message, command):
    assert DiagnosticConversationEngine.recognize_command(message) == command


def test_command_recognition_normalizes_case_and_accents():
    assert DiagnosticConversationEngine.recognize_command("COMEÇAR NOVAMENTE") == ConversationCommand.RESTART


@pytest.mark.parametrize("command", ["ajuda", "help"])
def test_help_returns_exact_deterministic_message(command):
    engine, dependency = subject()
    response = engine.process(ConversationInput(command, make_session()))
    assert response.response == HELP_MESSAGE
    assert dependency.calls == []


def test_help_without_session_does_not_start_workflow():
    engine, dependency = subject()
    response = engine.start_conversation("ajuda")
    assert response.session is None
    assert response.workflow_result is None
    assert dependency.calls == []


def test_status_does_not_call_session_engine():
    engine, dependency = subject()
    session = make_session()
    response = engine.continue_conversation(session, "status")
    assert dependency.calls == []
    assert response.session is session


@pytest.mark.parametrize(
    "fragment",
    ["Status: WAITING_USER", "interações: 1", "hypothesis-1", "0.75", "ASK_QUESTION", "Qual terminal"],
)
def test_status_contains_required_information(fragment):
    engine, _ = subject()
    response = engine.continue_conversation(make_session(), "status")
    assert fragment in response.response


def test_status_without_session_is_objective():
    engine, dependency = subject()
    response = engine.start_conversation("status")
    assert "Não há sessão" in response.response
    assert response.errors
    assert dependency.calls == []


@pytest.mark.parametrize("command", ["cancelar", "encerrar"])
def test_cancel_delegates_to_session_engine(command):
    engine, dependency = subject()
    response = engine.continue_conversation(make_session(), command)
    assert dependency.calls[0][0] == "cancel"
    assert response.status == DiagnosticSessionStatus.CANCELLED
    assert response.finished is True


def test_cancel_without_session_returns_error():
    engine, dependency = subject()
    response = engine.start_conversation("cancelar")
    assert response.errors == ("no active session",)
    assert dependency.calls == []


@pytest.mark.parametrize("command", ["reiniciar", "começar novamente"])
def test_restart_creates_new_session(command):
    engine, dependency = subject()
    old = make_session(session_id="old")
    response = engine.continue_conversation(old, command)
    assert dependency.calls[0][0] == "start"
    assert response.session.session_id != old.session_id


def test_restart_preserves_only_metadata():
    engine, _ = subject()
    old = make_session(metadata={"channel": "local"})
    response = engine.continue_conversation(old, "reiniciar")
    assert response.session.metadata == {"channel": "local"}
    assert response.session.answers == ()
    assert response.session.questions_asked == ()


def test_restart_without_session_returns_error():
    engine, dependency = subject()
    response = engine.start_conversation("reiniciar")
    assert response.errors
    assert dependency.calls == []


@pytest.mark.parametrize("command", ["humano", "atendente"])
def test_escalation_is_forwarded_to_session_engine(command):
    engine, dependency = subject()
    response = engine.continue_conversation(make_session(), command)
    assert dependency.calls[0][0] == "continue"
    assert response.status == DiagnosticSessionStatus.ESCALATED
    assert response.finished is True


def test_escalation_without_session_does_not_invent_state():
    engine, dependency = subject()
    response = engine.start_conversation("humano")
    assert response.session is None
    assert response.errors
    assert dependency.calls == []


def test_session_is_preserved_for_help():
    engine, _ = subject()
    session = make_session()
    assert engine.continue_conversation(session, "ajuda").session is session


def test_session_is_preserved_for_status():
    engine, _ = subject()
    session = make_session()
    assert engine.continue_conversation(session, "status").session is session


def test_conversation_response_fields():
    engine, _ = subject()
    response = engine.start_conversation("erro")
    assert isinstance(response, ConversationResponse)
    assert response.response
    assert response.session
    assert response.workflow_result
    assert response.decision
    assert response.status
    assert response.waiting_user is True
    assert response.waiting_confirmation is False


def test_conversation_input_fields():
    session = make_session()
    context = DiagnosticContext(message="erro")
    item = ConversationInput("mensagem", session, context)
    assert (item.message, item.session, item.context) == ("mensagem", session, context)


@pytest.mark.parametrize("command", list(ConversationCommand))
def test_conversation_command_values_are_stable(command):
    assert command.value == command.name


@pytest.mark.parametrize(
    ("status", "finished", "waiting_user", "waiting_confirmation"),
    [
        (DiagnosticSessionStatus.WAITING_USER, False, True, False),
        (DiagnosticSessionStatus.WAITING_CONFIRMATION, False, False, True),
        (DiagnosticSessionStatus.READY_FOR_TEST, False, False, False),
        (DiagnosticSessionStatus.READY_FOR_ACTION, False, False, False),
        (DiagnosticSessionStatus.COMPLETED, True, False, False),
        (DiagnosticSessionStatus.ESCALATED, True, False, False),
        (DiagnosticSessionStatus.CANCELLED, True, False, False),
        (DiagnosticSessionStatus.FAILED, True, False, False),
    ],
)
def test_response_flags_derive_from_status(status, finished, waiting_user, waiting_confirmation):
    engine, _ = subject()
    response = engine._without_turn("resposta", make_session(status), ConversationCommand.NORMAL)
    assert (response.finished, response.waiting_user, response.waiting_confirmation) == (
        finished,
        waiting_user,
        waiting_confirmation,
    )


def test_session_engine_error_is_captured():
    engine, dependency = subject()
    dependency.raise_error = RuntimeError("falha controlada")
    response = engine.start_conversation("erro")
    assert response.session is None
    assert response.errors == ("RuntimeError: falha controlada",)
    assert "RuntimeError" in response.response


def test_continue_error_preserves_existing_session():
    engine, dependency = subject()
    dependency.raise_error = RuntimeError("falha")
    session = make_session()
    response = engine.continue_conversation(session, "resposta")
    assert response.session is session


def test_dependency_injection():
    dependency = FakeSessionEngine()
    engine = DiagnosticConversationEngine(dependency)
    assert engine.session_engine is dependency


def test_default_constructor():
    assert isinstance(DiagnosticConversationEngine().session_engine, DiagnosticSessionEngine)


def test_models_are_frozen():
    item = ConversationInput("mensagem")
    with pytest.raises(FrozenInstanceError):
        item.message = "alterada"


def test_response_metadata_uses_defensive_copy():
    metadata = {"nested": {"value": 1}}
    response = ConversationResponse(
        response="ok",
        session=None,
        workflow_result=None,
        decision=None,
        status=None,
        finished=False,
        waiting_user=False,
        waiting_confirmation=False,
        metadata=metadata,
    )
    metadata["nested"]["value"] = 2
    assert response.metadata == {"nested": {"value": 1}}


def test_input_objects_are_not_mutated():
    engine, _ = subject()
    session = make_session()
    snapshot = deepcopy(session)
    engine.continue_conversation(session, "resposta")
    assert session == snapshot


def test_deterministic_response():
    first_engine, _ = subject()
    second_engine, _ = subject()
    first = first_engine.continue_conversation(make_session(), "status")
    second = second_engine.continue_conversation(make_session(), "status")
    assert first == second


def test_metadata_records_command_and_state_change():
    engine, _ = subject()
    response = engine.start_conversation("erro")
    assert response.metadata == {"command": "NORMAL", "state_changed": True, "interaction_count": 1}


def test_help_metadata_is_deterministic():
    engine, _ = subject()
    response = engine.start_conversation("ajuda")
    assert response.metadata == {"command": "HELP", "state_changed": False, "interaction_count": 0}


def test_process_rejects_wrong_input_type():
    engine, _ = subject()
    with pytest.raises(TypeError):
        engine.process("mensagem")


def test_empty_normal_message_error_is_returned():
    engine = DiagnosticConversationEngine(DiagnosticSessionEngine())
    response = engine.start_conversation("   ")
    assert response.errors
    assert response.session is None


def test_response_never_claims_command_execution():
    engine, _ = subject()
    for command in ("ajuda", "status", "cancelar", "humano"):
        response = engine.continue_conversation(make_session(), command)
        assert "executado" not in response.response.lower()
        assert "executei" not in response.response.lower()


def test_files_are_utf8_without_bom():
    paths = [
        "app/services/diagnostic_engine/conversation_models.py",
        "app/services/diagnostic_engine/conversation_engine.py",
        "app/services/diagnostic_engine/__init__.py",
        "tests/services/diagnostic_engine/test_conversation_engine.py",
    ]
    for path in paths:
        content = Path(path).read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
