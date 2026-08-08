from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.diagnostic_engine import (
    DiagnosticExecutionEngine,
    DiagnosticSessionEngine,
    DiagnosticSessionStatus,
)
from app.services.diagnostic_engine.conversation_engine import DiagnosticConversationEngine
from app.services.diagnostic_engine.decision_models import Decision, DecisionPriority, DecisionType
from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.evidence_models import Evidence, EvidenceResult
from app.services.diagnostic_engine.execution_models import ExecutionResult, ExecutionStatus
from app.services.diagnostic_engine.execution_policy import DiagnosticExecutionPolicy
from app.services.diagnostic_engine.knowledge_models import DiagnosticTest
from app.services.diagnostic_engine.workflow_models import WorkflowResult


def decision(kind=DecisionType.ASK_QUESTION):
    return Decision(
        decision_type=kind,
        priority=DecisionPriority.NORMAL,
        title="Decisão",
        message="Mensagem existente.",
        reasoning=("regra",),
        confidence=0.75,
        incident_id="incident-1",
        requires_human=kind == DecisionType.ESCALATE_TO_HUMAN,
        risk_level=RiskLevel.LOW,
        next_question="Qual terminal?" if kind == DecisionType.ASK_QUESTION else None,
        recommended_test="Ping" if kind == DecisionType.RUN_TEST else None,
        recommended_action="Reiniciar serviço" if kind in {DecisionType.REQUEST_CONFIRMATION, DecisionType.RECOMMEND_ACTION} else None,
        confirmation_required=kind == DecisionType.REQUEST_CONFIRMATION,
        completion_reason="Confirmado" if kind == DecisionType.COMPLETE else None,
        metadata={"source": "workflow"},
    )


def workflow_result(kind=DecisionType.ASK_QUESTION, *, with_expected_result=False):
    evidence = Evidence.neutral("resposta")
    tests = []
    if with_expected_result:
        tests = [DiagnosticTest("ping", "Ping", "Consultar rede", "ping", RiskLevel.READ_ONLY, False, False, ["resposta"])]
    hypothesis = SimpleNamespace(
        incident_id="incident-1",
        confidence=0.75,
        requires_human=False,
        risk_level=RiskLevel.LOW,
        next_questions=[],
        recommended_tests=tests,
        recommended_actions=[],
    )
    evidence_result = EvidenceResult(
        evidence=evidence,
        updated_hypotheses=[hypothesis],
        hypothesis_updates=[],
        selected_question=None,
        known_information={"terminal": "caixa 1"},
        unresolved_information=[],
        evidence_history=[evidence],
    )
    return WorkflowResult(
        hypotheses=[hypothesis],
        evidence_result=evidence_result,
        decision=decision(kind),
        success=True,
    )


class FakeWorkflow:
    def __init__(self, *results):
        self.results = list(results or (workflow_result(),))
        self.calls = []

    def run(self, message, **kwargs):
        self.calls.append((message, deepcopy(kwargs)))
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


class SpyExecution:
    def __init__(self, result=None, error=None, policy=None):
        self.delegate = DiagnosticExecutionEngine(policy)
        self.result = result
        self.error = error
        self.calls = []
        self.executed = False

    def build_execution_plan(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if self.error:
            raise self.error
        return self.result if self.result is not None else self.delegate.build_execution_plan(**kwargs)


def engine(*results, execution=None):
    workflow = FakeWorkflow(*results)
    execution = execution or SpyExecution()
    return DiagnosticSessionEngine(workflow, execution_engine=execution), workflow, execution


def start(subject):
    return subject.start_session("Sistema não abre", session_id="session-1")


def test_start_creates_execution_result():
    subject, _, _ = engine()
    assert start(subject).session.execution_result is not None


def test_start_creates_execution_plan():
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST))
    assert start(subject).session.execution_plan is not None


def test_execution_plan_derives_from_diagnostic_plan():
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST))
    session = start(subject).session
    assert session.execution_plan.metadata["source_diagnostic_plan_id"] == session.diagnostic_plan.plan_id


def test_ask_question_generates_no_action():
    subject, _, _ = engine()
    assert start(subject).session.execution_plan.actions == ()


def test_safe_run_test_generates_descriptive_action():
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST))
    action = start(subject).session.execution_plan.actions[0]
    assert action.action_name == "ping_host"
    assert "no operation was executed" in action.description


def test_verify_result_generates_descriptive_action():
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST, with_expected_result=True))
    actions = start(subject).session.execution_plan.actions
    assert [action.action_name for action in actions] == ["ping_host", "verify_result"]


def test_request_confirmation_is_blocked():
    subject, _, _ = engine(workflow_result(DecisionType.REQUEST_CONFIRMATION))
    action = start(subject).session.execution_plan.actions[0]
    assert action.status == ExecutionStatus.BLOCKED
    assert action.requires_confirmation is True


def test_recommend_action_is_manual():
    policy = DiagnosticExecutionPolicy(allow_state_changing_actions=True)
    subject, _, _ = engine(workflow_result(DecisionType.RECOMMEND_ACTION), execution=SpyExecution(policy=policy))
    assert start(subject).session.execution_plan.actions[0].action_name == "recommend_manual_action"


def test_escalation_creates_blocked_description():
    subject, _, _ = engine(workflow_result(DecisionType.ESCALATE_TO_HUMAN))
    session = start(subject).session
    assert session.execution_plan.status == ExecutionStatus.BLOCKED
    assert session.execution_plan.actions[0].requires_human is True


def test_complete_does_not_create_follow_up_actions():
    subject, _, _ = engine(workflow_result(DecisionType.COMPLETE))
    assert start(subject).session.execution_plan.actions == ()


def test_start_passes_none_as_previous_execution_plan():
    subject, _, execution = engine()
    start(subject)
    assert execution.calls[0]["previous_execution_plan"] is None


def test_continue_passes_previous_execution_plan():
    subject, _, execution = engine(workflow_result(DecisionType.RUN_TEST), workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    subject.continue_session(first, "Caixa 1")
    assert execution.calls[1]["previous_execution_plan"] == first.execution_plan


@pytest.mark.parametrize("status", [ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED])
def test_continue_preserves_terminal_execution_status(status):
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST), workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    action = replace(first.execution_plan.actions[0], status=status)
    terminal = {
        "completed_actions": (action.action_id,) if status == ExecutionStatus.SUCCESS else (),
        "failed_actions": (action.action_id,) if status == ExecutionStatus.FAILED else (),
        "cancelled_actions": (action.action_id,) if status == ExecutionStatus.CANCELLED else (),
    }
    previous_plan = replace(first.execution_plan, actions=(action,), current_action_id=None, **terminal)
    prepared = replace(first, execution_plan=previous_plan)
    second = subject.continue_session(prepared, "Caixa 1").session
    assert second.execution_plan.actions[0].status == status


def test_equivalent_action_is_not_duplicated():
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST), workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    second = subject.continue_session(first, "Caixa 1").session
    assert len(second.execution_plan.actions) == 1


def test_previous_session_is_not_mutated():
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST), workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    snapshot = deepcopy(first)
    subject.continue_session(first, "Caixa 1")
    assert first == snapshot


def test_previous_diagnostic_plan_is_not_mutated():
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST), workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    snapshot = deepcopy(first.diagnostic_plan)
    subject.continue_session(first, "Caixa 1")
    assert first.diagnostic_plan == snapshot


def test_previous_execution_plan_is_not_mutated():
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST), workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    snapshot = deepcopy(first.execution_plan)
    subject.continue_session(first, "Caixa 1")
    assert first.execution_plan == snapshot


def test_previous_memory_is_not_mutated():
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST), workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    snapshot = deepcopy(first.memory_snapshot)
    subject.continue_session(first, "Caixa 1")
    assert first.memory_snapshot == snapshot


@pytest.mark.parametrize("command", ["status", "cancelar", "humano"])
def test_non_workflow_commands_preserve_execution_fields(command):
    subject, _, execution = engine(workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    result = subject.continue_session(first, command)
    assert result.session.execution_plan == first.execution_plan
    assert result.session.execution_result == first.execution_result
    assert len(execution.calls) == 1


def test_restart_creates_new_execution_plan():
    subject, _, execution = engine(workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    restarted = subject.continue_session(first, "reiniciar").session
    assert restarted.execution_plan is not first.execution_plan
    assert len(execution.calls) == 2


def test_help_preserves_execution_fields():
    subject, _, execution = engine(workflow_result(DecisionType.RUN_TEST))
    session = start(subject).session
    response = DiagnosticConversationEngine(subject).continue_conversation(session, "ajuda")
    assert response.session is session
    assert response.session.execution_plan == session.execution_plan
    assert len(execution.calls) == 1


def test_failed_execution_result_does_not_break_session():
    failed = ExecutionResult(success=False, errors=("falha controlada",))
    subject, _, _ = engine(execution=SpyExecution(result=failed))
    turn = start(subject)
    assert turn.session.execution_result == failed
    assert turn.session.execution_plan is None
    assert turn.session.status == DiagnosticSessionStatus.WAITING_USER


def test_execution_errors_are_recorded_without_duplicates():
    failed = ExecutionResult(success=False, errors=("falha", "falha"))
    subject, _, _ = engine(execution=SpyExecution(result=failed))
    assert start(subject).session.metadata["execution_errors"] == ("falha",)


def test_execution_exception_is_captured():
    subject, _, _ = engine(execution=SpyExecution(error=RuntimeError("falha inesperada")))
    turn = start(subject)
    assert turn.session.execution_result.success is False
    assert "RuntimeError" in turn.session.execution_result.errors[0]
    assert turn.session.status == DiagnosticSessionStatus.WAITING_USER


def test_execution_failure_preserves_workflow_decision():
    subject, _, _ = engine(execution=SpyExecution(error=RuntimeError("falha")))
    turn = start(subject)
    assert turn.session.decisions[-1] == turn.workflow_result.decision


def test_execution_failure_preserves_diagnostic_plan():
    subject, _, _ = engine(execution=SpyExecution(error=RuntimeError("falha")))
    assert start(subject).session.diagnostic_plan is not None


def test_execution_failure_does_not_change_response_or_status():
    normal, _, _ = engine()
    failing, _, _ = engine(execution=SpyExecution(error=RuntimeError("falha")))
    normal_turn = start(normal)
    failed_turn = start(failing)
    assert failed_turn.response_message == normal_turn.response_message == "Qual terminal?"
    assert failed_turn.session.status == normal_turn.session.status


def test_default_constructor_builds_execution_engine():
    assert isinstance(DiagnosticSessionEngine().execution_engine, DiagnosticExecutionEngine)


def test_custom_execution_engine_injection():
    execution = SpyExecution()
    subject = DiagnosticSessionEngine(FakeWorkflow(), execution_engine=execution)
    assert subject.execution_engine is execution


def test_custom_execution_policy_is_used():
    policy = DiagnosticExecutionPolicy(allow_unknown_target=True)
    execution = SpyExecution(policy=policy)
    subject, _, _ = engine(execution=execution)
    start(subject)
    assert execution.delegate.policy is policy


def test_start_is_deterministic(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.session_engine.time.monotonic", lambda: 1.0)
    first, _, _ = engine(workflow_result(DecisionType.RUN_TEST))
    second, _, _ = engine(workflow_result(DecisionType.RUN_TEST))
    assert start(first).session == start(second).session


def test_continue_is_deterministic(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.session_engine.time.monotonic", lambda: 1.0)
    first, _, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    second, _, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    assert first.continue_session(start(first).session, "Caixa 1").session == second.continue_session(start(second).session, "Caixa 1").session


def test_no_action_is_running_or_executed():
    execution = SpyExecution()
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST), execution=execution)
    session = start(subject).session
    assert all(action.status != ExecutionStatus.RUNNING for action in session.execution_plan.actions)
    assert execution.executed is False


def test_workflow_result_is_not_mutated():
    result = workflow_result(DecisionType.RUN_TEST)
    snapshot = deepcopy(result)
    subject, _, _ = engine(result)
    start(subject)
    assert result == snapshot


def test_session_model_defaults_are_compatible():
    from app.services.diagnostic_engine.session_models import DiagnosticSession

    session = DiagnosticSession("id", DiagnosticSessionStatus.NEW, "erro", "erro")
    assert session.execution_plan is None and session.execution_result is None


def test_session_model_defensively_copies_execution_fields():
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST))
    session = start(subject).session
    copied = replace(session, execution_plan=session.execution_plan, execution_result=session.execution_result)
    assert copied.execution_plan == session.execution_plan
    assert copied.execution_plan is not session.execution_plan
    assert copied.execution_result is not session.execution_result


def test_public_imports_remain_available():
    from app.services.diagnostic_engine import DiagnosticExecutionEngine as PublicExecution

    assert PublicExecution is DiagnosticExecutionEngine


def test_files_are_utf8_without_bom():
    root = Path(__file__).parents[3]
    for path in (
        root / "app/services/diagnostic_engine/session_models.py",
        root / "app/services/diagnostic_engine/session_engine.py",
        Path(__file__),
    ):
        content = path.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
