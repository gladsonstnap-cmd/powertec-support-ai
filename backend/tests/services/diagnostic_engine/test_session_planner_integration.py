from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.diagnostic_engine import DiagnosticPlannerEngine, DiagnosticSessionEngine, DiagnosticSessionStatus
from app.services.diagnostic_engine.conversation_engine import DiagnosticConversationEngine
from app.services.diagnostic_engine.decision_models import Decision, DecisionPriority, DecisionType
from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.evidence_models import Evidence, EvidenceResult
from app.services.diagnostic_engine.planner_models import DiagnosticPlanResult, DiagnosticPlanStatus, PlanStepStatus
from app.services.diagnostic_engine.planner_policy import DiagnosticPlannerPolicy
from app.services.diagnostic_engine.workflow_models import WorkflowResult


def decision(kind=DecisionType.ASK_QUESTION):
    return Decision(
        decision_type=kind,
        priority=DecisionPriority.NORMAL,
        title="Decisão",
        message="Mensagem existente.",
        reasoning=("regra",),
        confidence=.75,
        incident_id="incident-1",
        requires_human=kind == DecisionType.ESCALATE_TO_HUMAN,
        risk_level=RiskLevel.LOW,
        next_question="Qual terminal?" if kind == DecisionType.ASK_QUESTION else None,
        recommended_test="Ping" if kind == DecisionType.RUN_TEST else None,
        recommended_action="Reiniciar serviço" if kind in {DecisionType.REQUEST_CONFIRMATION, DecisionType.RECOMMEND_ACTION} else None,
        confirmation_required=kind == DecisionType.REQUEST_CONFIRMATION,
        completion_reason="Confirmado" if kind == DecisionType.COMPLETE else None,
    )


def workflow_result(kind=DecisionType.ASK_QUESTION):
    evidence = Evidence.neutral("resposta")
    hypothesis = SimpleNamespace(
        incident_id="incident-1",
        confidence=.75,
        requires_human=False,
        risk_level=RiskLevel.LOW,
        next_questions=[],
        recommended_tests=[],
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
        self.calls.append((message, kwargs))
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


class SpyPlanner:
    def __init__(self, result=None, error=None, policy=None):
        self.delegate = DiagnosticPlannerEngine(policy)
        self.result = result
        self.error = error
        self.calls = []
        self.executed = False

    def build_plan(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if self.error:
            raise self.error
        return self.result or self.delegate.build_plan(**kwargs)


def engine(*results, planner=None):
    workflow = FakeWorkflow(*results)
    planner = planner or SpyPlanner()
    return DiagnosticSessionEngine(workflow, planner_engine=planner), workflow, planner


def start(subject):
    return subject.start_session("Sistema não abre", session_id="session-1")


def test_start_creates_diagnostic_plan():
    subject, _, _ = engine()
    assert start(subject).session.diagnostic_plan is not None


def test_start_creates_planner_result():
    subject, _, _ = engine()
    assert start(subject).session.planner_result.success


def test_plan_uses_workflow_decision():
    subject, _, _ = engine(workflow_result(DecisionType.RUN_TEST))
    session = start(subject).session
    assert session.diagnostic_plan.created_from_decision_type == DecisionType.RUN_TEST
    assert session.decisions[-1] == decision(DecisionType.RUN_TEST)


@pytest.mark.parametrize(
    ("kind", "plan_status", "session_status"),
    [
        (DecisionType.ASK_QUESTION, DiagnosticPlanStatus.WAITING_USER, DiagnosticSessionStatus.WAITING_USER),
        (DecisionType.RUN_TEST, DiagnosticPlanStatus.ACTIVE, DiagnosticSessionStatus.READY_FOR_TEST),
        (DecisionType.REQUEST_CONFIRMATION, DiagnosticPlanStatus.WAITING_CONFIRMATION, DiagnosticSessionStatus.WAITING_CONFIRMATION),
        (DecisionType.RECOMMEND_ACTION, DiagnosticPlanStatus.ACTIVE, DiagnosticSessionStatus.READY_FOR_ACTION),
        (DecisionType.ESCALATE_TO_HUMAN, DiagnosticPlanStatus.ESCALATED, DiagnosticSessionStatus.ESCALATED),
        (DecisionType.COMPLETE, DiagnosticPlanStatus.COMPLETED, DiagnosticSessionStatus.COMPLETED),
    ],
)
def test_decision_maps_to_plan_without_changing_session_mapping(kind, plan_status, session_status):
    subject, _, _ = engine(workflow_result(kind))
    session = start(subject).session
    assert session.diagnostic_plan.status == plan_status
    assert session.status == session_status


def test_start_passes_all_planner_inputs():
    subject, _, planner = engine()
    turn = start(subject)
    call = planner.calls[0]
    assert call["hypotheses"] == turn.workflow_result.hypotheses
    assert call["decision"] == turn.workflow_result.decision
    assert call["evidence_result"] == turn.workflow_result.evidence_result
    assert call["knowledge_result"] == turn.workflow_result.knowledge_result
    assert call["memory_snapshot"] == turn.session.memory_snapshot
    assert call["previous_plan"] is None


def test_continue_passes_previous_plan():
    subject, _, planner = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    subject.continue_session(first, "Caixa 1")
    assert planner.calls[1]["previous_plan"] == first.diagnostic_plan


def test_continue_saves_new_plan_and_result():
    subject, _, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    second = subject.continue_session(start(subject).session, "Caixa 1").session
    assert second.diagnostic_plan.created_from_decision_type == DecisionType.RUN_TEST
    assert second.planner_result.plan == second.diagnostic_plan


@pytest.mark.parametrize("terminal_status", [PlanStepStatus.COMPLETED, PlanStepStatus.SKIPPED, PlanStepStatus.FAILED])
def test_continue_preserves_terminal_steps(terminal_status):
    subject, _, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    original_step = replace(first.diagnostic_plan.steps[0], status=terminal_status)
    state_fields = {"completed_step_ids": (), "skipped_step_ids": (), "failed_step_ids": ()}
    state_fields[f"{terminal_status.value.lower()}_step_ids"] = (original_step.step_id,)
    previous_plan = replace(first.diagnostic_plan, steps=(original_step,), current_step_id=None, **state_fields)
    prepared = replace(first, diagnostic_plan=previous_plan)
    second = subject.continue_session(prepared, "Caixa 1").session
    assert original_step in second.diagnostic_plan.steps


def test_equivalent_step_is_not_duplicated():
    subject, _, _ = engine(workflow_result(), workflow_result())
    first = start(subject).session
    completed = replace(first.diagnostic_plan.steps[0], status=PlanStepStatus.COMPLETED)
    previous = replace(first.diagnostic_plan, steps=(completed,), current_step_id=None, completed_step_ids=(completed.step_id,))
    second = subject.continue_session(replace(first, diagnostic_plan=previous), "Caixa 1").session
    assert len(second.diagnostic_plan.steps) == 1


def test_previous_session_is_not_mutated():
    subject, _, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    snapshot = deepcopy(first)
    subject.continue_session(first, "Caixa 1")
    assert first == snapshot


def test_previous_plan_is_not_mutated():
    subject, _, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    snapshot = deepcopy(first.diagnostic_plan)
    subject.continue_session(first, "Caixa 1")
    assert first.diagnostic_plan == snapshot


def test_previous_memory_is_not_mutated():
    subject, _, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    first = start(subject).session
    snapshot = deepcopy(first.memory_snapshot)
    subject.continue_session(first, "Caixa 1")
    assert first.memory_snapshot == snapshot


@pytest.mark.parametrize("command", ["status", "cancelar", "humano"])
def test_non_workflow_commands_preserve_plan(command):
    subject, _, planner = engine()
    first = start(subject).session
    result = subject.continue_session(first, command)
    assert result.session.diagnostic_plan == first.diagnostic_plan
    assert result.session.planner_result == first.planner_result
    assert len(planner.calls) == 1


def test_restart_creates_new_plan():
    subject, _, planner = engine()
    first = start(subject).session
    restarted = subject.continue_session(first, "reiniciar").session
    assert restarted.diagnostic_plan is not None
    assert restarted.diagnostic_plan is not first.diagnostic_plan
    assert len(planner.calls) == 2


def test_help_preserves_plan_without_calling_planner():
    subject, _, planner = engine()
    session = start(subject).session
    response = DiagnosticConversationEngine(subject).continue_conversation(session, "ajuda")
    assert response.session is session
    assert response.session.diagnostic_plan == session.diagnostic_plan
    assert len(planner.calls) == 1


def test_unsuccessful_planner_result_does_not_break_session():
    failed = DiagnosticPlanResult(success=False, errors=("falha controlada",))
    subject, _, _ = engine(planner=SpyPlanner(result=failed))
    turn = start(subject)
    assert turn.session.diagnostic_plan is None
    assert turn.session.planner_result == failed
    assert turn.session.status == DiagnosticSessionStatus.WAITING_USER


def test_planner_error_is_recorded_in_metadata():
    failed = DiagnosticPlanResult(success=False, errors=("falha controlada",))
    subject, _, _ = engine(planner=SpyPlanner(result=failed))
    assert start(subject).session.metadata["planner_errors"] == ("falha controlada",)


def test_planner_exception_is_captured():
    subject, _, _ = engine(planner=SpyPlanner(error=RuntimeError("falha inesperada")))
    turn = start(subject)
    assert turn.session.planner_result.success is False
    assert "RuntimeError" in turn.session.planner_result.errors[0]
    assert turn.session.status == DiagnosticSessionStatus.WAITING_USER


def test_planner_failure_does_not_change_workflow_decision():
    subject, _, _ = engine(planner=SpyPlanner(error=RuntimeError("falha")))
    turn = start(subject)
    assert turn.workflow_result.decision == decision()
    assert turn.session.decisions[-1] == turn.workflow_result.decision


def test_planner_failure_does_not_change_response_message():
    normal, _, _ = engine()
    failing, _, _ = engine(planner=SpyPlanner(error=RuntimeError("falha")))
    assert start(normal).response_message == start(failing).response_message == "Qual terminal?"


def test_default_constructor_builds_planner():
    assert isinstance(DiagnosticSessionEngine().planner_engine, DiagnosticPlannerEngine)


def test_custom_planner_injection():
    planner = SpyPlanner()
    subject = DiagnosticSessionEngine(FakeWorkflow(), planner_engine=planner)
    assert subject.planner_engine is planner


def test_custom_planner_policy_is_used():
    policy = DiagnosticPlannerPolicy(max_steps=1)
    planner = SpyPlanner(policy=policy)
    subject, _, _ = engine(planner=planner)
    start(subject)
    assert planner.delegate.policy is policy


def test_start_plan_is_deterministic(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.session_engine.time.monotonic", lambda: 1.0)
    first, _, _ = engine()
    second, _, _ = engine()
    assert start(first).session == start(second).session


def test_continue_plan_is_deterministic(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.session_engine.time.monotonic", lambda: 1.0)
    first, _, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    second, _, _ = engine(workflow_result(), workflow_result(DecisionType.RUN_TEST))
    assert first.continue_session(start(first).session, "Caixa 1").session == second.continue_session(start(second).session, "Caixa 1").session


def test_planner_does_not_execute_actions_or_tests():
    planner = SpyPlanner()
    subject, _, _ = engine(workflow_result(DecisionType.RECOMMEND_ACTION), planner=planner)
    start(subject)
    assert planner.executed is False


def test_workflow_result_is_not_mutated():
    result = workflow_result()
    snapshot = deepcopy(result)
    subject, _, _ = engine(result)
    start(subject)
    assert result == snapshot


def test_session_model_defaults_are_compatible():
    from app.services.diagnostic_engine.session_models import DiagnosticSession

    session = DiagnosticSession("id", DiagnosticSessionStatus.NEW, "erro", "erro")
    assert session.diagnostic_plan is None and session.planner_result is None


def test_session_model_defensively_copies_planner_fields():
    subject, _, _ = engine()
    session = start(subject).session
    copied = replace(session, diagnostic_plan=session.diagnostic_plan, planner_result=session.planner_result)
    assert copied.diagnostic_plan == session.diagnostic_plan
    assert copied.diagnostic_plan is not session.diagnostic_plan


def test_public_import_remains_available():
    from app.services.diagnostic_engine import DiagnosticPlannerEngine as PublicPlanner

    assert PublicPlanner is DiagnosticPlannerEngine


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
