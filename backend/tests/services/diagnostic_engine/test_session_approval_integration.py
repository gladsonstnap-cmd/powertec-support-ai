import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    DiagnosticApprovalEngine,
    DiagnosticSession,
    DiagnosticSessionEngine,
    DiagnosticSessionStatus,
)
from app.services.diagnostic_engine.approval_models import ApprovalActor, ApprovalResult, ApprovalStatus, ApprovalType
from app.services.diagnostic_engine.approval_policy import DiagnosticApprovalPolicy
from app.services.diagnostic_engine.conversation_engine import DiagnosticConversationEngine
from app.services.diagnostic_engine.decision_models import Decision, DecisionPriority, DecisionType
from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction, ExecutionPlan, ExecutionResult, ExecutionRisk, ExecutionStatus, ExecutionTarget,
)
from app.services.diagnostic_engine.planner_models import DiagnosticPlanResult
from app.services.diagnostic_engine.workflow_models import WorkflowResult


def action(risk=ExecutionRisk.MEDIUM, **overrides):
    values = {
        "action_id": "action-1", "action_name": "restart_service", "title": "Reiniciar serviço",
        "description": "Descrição segura; nada foi executado.", "target": ExecutionTarget.WINDOWS,
        "status": ExecutionStatus.READY, "risk": risk, "parameters": (), "timeout_seconds": 30,
        "requires_confirmation": risk != ExecutionRisk.LOW, "requires_human": risk in {ExecutionRisk.HIGH, ExecutionRisk.CRITICAL},
        "metadata": {"action_kind": "state_changing"},
    }
    values.update(overrides)
    return ExecutionAction(**values)


def execution_plan(item=None):
    selected = action() if item is None else item
    return ExecutionPlan("plan-1", ExecutionStatus.READY, (selected,), selected.action_id)


def session(item=None, **overrides):
    selected = action() if item is None else item
    values = {
        "session_id": "session-1", "status": DiagnosticSessionStatus.READY_FOR_ACTION,
        "original_message": "Erro", "last_message": "Erro", "execution_plan": execution_plan(selected),
        "execution_result": ExecutionResult(True, execution_plan(selected), selected),
    }
    values.update(overrides)
    return DiagnosticSession(**values)


def actor(actor_type=ApprovalType.HUMAN_TECHNICIAN):
    return ApprovalActor(f"actor-{actor_type.value.lower()}", actor_type)


def diagnostic_decision():
    return Decision(
        decision_type=DecisionType.RECOMMEND_ACTION, priority=DecisionPriority.NORMAL,
        title="Recomendação", message="Aprovação necessária", reasoning=("regra",), confidence=0.8,
        incident_id="incident-1", requires_human=False, risk_level=RiskLevel.MEDIUM,
        next_question=None, recommended_test=None, recommended_action="Reiniciar serviço",
        confirmation_required=False, completion_reason=None,
    )


class FakeWorkflow:
    def run(self, message, **kwargs):
        return WorkflowResult(decision=diagnostic_decision(), success=True)


class FakePlanner:
    def build_plan(self, **kwargs):
        return DiagnosticPlanResult(success=False, errors=("planner omitted in integration fixture",))


class FakeExecution:
    def __init__(self, item):
        self.item = item
        self.executed = False

    def build_execution_plan(self, **kwargs):
        source = execution_plan(self.item)
        return ExecutionResult(True, source, self.item)


def integrated_engine(item=None, approval_engine=None):
    selected = action() if item is None else item
    return DiagnosticSessionEngine(
        workflow_engine=FakeWorkflow(), planner_engine=FakePlanner(),
        execution_engine=FakeExecution(selected), approval_engine=approval_engine,
    )


def request_turn(subject=None, source=None, **kwargs):
    subject = subject or DiagnosticSessionEngine()
    source = source or session()
    return subject.request_action_approval(source, "action-1", now_monotonic=10, **kwargs)


def approved_session(subject=None, source=None, actor_type=ApprovalType.USER_CONFIRMATION):
    subject = subject or DiagnosticSessionEngine()
    requested = request_turn(subject, source).session
    approval_id = requested.approval_requests[-1].approval_id
    decided = subject.decide_action_approval(
        requested, approval_id, ApprovalStatus.APPROVED, actor(actor_type), 11,
    ).session
    return subject, decided, approval_id


def granted_session(subject=None, source=None):
    subject, decided, approval_id = approved_session(subject, source)
    granted = subject.create_action_grant(decided, approval_id, 12).session
    return subject, granted, granted.approval_grants[-1]


def test_session_approval_defaults_are_empty():
    source = DiagnosticSession("id", DiagnosticSessionStatus.NEW, "erro", "erro")
    assert source.approval_requests == () and source.approval_decisions == ()
    assert source.approval_grants == () and source.approval_result is None


def test_start_without_required_approval_keeps_empty_history():
    turn = integrated_engine(action(risk=ExecutionRisk.LOW)).start_session("Erro", session_id="session-1")
    assert turn.session.approval_requests == () and turn.session.approval_result is None


@pytest.mark.parametrize("risk", [ExecutionRisk.MEDIUM, ExecutionRisk.HIGH, ExecutionRisk.CRITICAL])
def test_start_creates_request_for_risk_requiring_approval(risk):
    turn = integrated_engine(action(risk=risk)).start_session("Erro", session_id="session-1")
    assert len(turn.session.approval_requests) == 1
    assert turn.session.approval_requests[0].risk == risk


def test_start_stores_current_approval_result():
    turn = integrated_engine().start_session("Erro", session_id="session-1")
    assert turn.session.approval_result.success
    assert turn.session.approval_result.request == turn.session.approval_requests[0]


def test_start_does_not_create_decision_or_grant():
    source = integrated_engine().start_session("Erro", session_id="session-1").session
    assert source.approval_decisions == () and source.approval_grants == ()


def test_continue_does_not_duplicate_equivalent_pending_request():
    subject = integrated_engine()
    first = subject.start_session("Erro", session_id="session-1").session
    second = subject.continue_session(first, "Ainda ocorre").session
    assert len(second.approval_requests) == 1


def test_request_action_approval_locates_action():
    turn = request_turn()
    assert turn.session.approval_requests[0].action_id == "action-1"


@pytest.mark.parametrize("action_id", ["missing", "", None])
def test_request_action_approval_rejects_missing_action(action_id):
    turn = DiagnosticSessionEngine().request_action_approval(session(), action_id)
    assert not turn.session.approval_result.success and turn.session.approval_requests == ()


def test_request_action_approval_adds_request():
    turn = request_turn()
    assert turn.state_changed and len(turn.session.approval_requests) == 1


def test_request_action_approval_does_not_create_grant():
    assert request_turn().session.approval_grants == ()


def test_duplicate_explicit_request_is_not_added():
    subject = DiagnosticSessionEngine()
    first = request_turn(subject).session
    second = request_turn(subject, first).session
    assert len(second.approval_requests) == 1


@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.CANCELLED, ApprovalStatus.EXPIRED])
def test_decide_action_approval_records_terminal_decision(status):
    subject = DiagnosticSessionEngine(); requested = request_turn(subject).session
    result = subject.decide_action_approval(requested, requested.approval_requests[0].approval_id, status, actor(ApprovalType.USER_CONFIRMATION), 11)
    assert result.session.approval_decisions[-1].status == status


def test_decision_preserves_request():
    subject = DiagnosticSessionEngine(); requested = request_turn(subject).session; before = requested.approval_requests
    decided = subject.decide_action_approval(requested, before[0].approval_id, ApprovalStatus.APPROVED, actor(ApprovalType.USER_CONFIRMATION), 11).session
    assert decided.approval_requests == before


def test_decision_does_not_create_grant():
    _, decided, _ = approved_session()
    assert decided.approval_grants == ()


def test_missing_request_decision_is_controlled_failure():
    turn = DiagnosticSessionEngine().decide_action_approval(session(), "missing", ApprovalStatus.APPROVED, actor(), 11)
    assert not turn.session.approval_result.success


def test_create_grant_after_approved_decision():
    _, granted, grant = granted_session()
    assert granted.approval_result.success and grant.action_id == "action-1"


def test_create_grant_without_approved_decision_fails():
    subject = DiagnosticSessionEngine(); requested = request_turn(subject).session
    turn = subject.create_action_grant(requested, requested.approval_requests[0].approval_id, 11)
    assert not turn.session.approval_result.success and turn.session.approval_grants == ()


def test_grant_preserves_approved_action_snapshot():
    _, granted, grant = granted_session()
    assert grant.action_snapshot == granted.execution_plan.actions[0]


def test_consume_grant_appends_used_snapshot():
    subject, granted, grant = granted_session()
    consumed = subject.consume_action_grant(granted, grant.grant_id, grant.action_id, 13).session
    assert len(consumed.approval_grants) == 2 and consumed.approval_grants[-1].used


def test_consume_preserves_original_grant():
    subject, granted, grant = granted_session(); before = deepcopy(grant)
    subject.consume_action_grant(granted, grant.grant_id, grant.action_id, 13)
    assert grant == before and grant.used is False


@pytest.mark.parametrize("missing", ["grant", "action"])
def test_consume_missing_component_is_controlled_failure(missing):
    subject, granted, grant = granted_session()
    grant_id = "missing" if missing == "grant" else grant.grant_id
    action_id = "missing" if missing == "action" else grant.action_id
    result = subject.consume_action_grant(granted, grant_id, action_id, 13)
    assert not result.session.approval_result.success


def test_consume_does_not_change_action_status():
    subject, granted, grant = granted_session(); status = granted.execution_plan.actions[0].status
    consumed = subject.consume_action_grant(granted, grant.grant_id, grant.action_id, 13).session
    assert consumed.execution_plan.actions[0].status == status != ExecutionStatus.SUCCESS


def test_approved_does_not_change_action_status():
    _, decided, _ = approved_session()
    assert decided.execution_plan.actions[0].status == ExecutionStatus.READY


@pytest.mark.parametrize("method", ["request", "decide", "grant", "consume"])
def test_previous_session_is_not_mutated(method):
    subject = DiagnosticSessionEngine(); source = session(); before = deepcopy(source)
    if method == "request": subject.request_action_approval(source, "action-1")
    elif method == "decide":
        requested = request_turn(subject, source).session; snap = deepcopy(requested)
        subject.decide_action_approval(requested, requested.approval_requests[0].approval_id, ApprovalStatus.APPROVED, actor(ApprovalType.USER_CONFIRMATION), 11)
        assert requested == snap
    elif method == "grant":
        _, decided, approval_id = approved_session(subject, source); snap = deepcopy(decided)
        subject.create_action_grant(decided, approval_id, 12); assert decided == snap
    else:
        _, granted, grant = granted_session(subject, source); snap = deepcopy(granted)
        subject.consume_action_grant(granted, grant.grant_id, grant.action_id, 13); assert granted == snap
    assert source == before


def test_session_defensively_copies_approval_collections():
    requested = request_turn().session; items = list(requested.approval_requests)
    copied = replace(session(), approval_requests=items, approval_result=requested.approval_result)
    items.clear()
    assert len(copied.approval_requests) == 1 and copied.approval_requests is not requested.approval_requests


@pytest.mark.parametrize("field", ["execution_plan", "diagnostic_plan", "memory_snapshot"])
def test_approval_flow_preserves_diagnostic_snapshots(field):
    source = session(); before = deepcopy(getattr(source, field))
    request_turn(source=source)
    assert getattr(source, field) == before


@pytest.mark.parametrize("command", ["status", "cancelar", "humano"])
def test_session_commands_preserve_approvals(command):
    subject = DiagnosticSessionEngine(); requested = request_turn(subject).session
    turn = subject.continue_session(requested, command)
    assert turn.session.approval_requests == requested.approval_requests


def test_restart_starts_without_old_approvals():
    subject = integrated_engine(); requested = subject.start_session("Erro", session_id="session-1").session
    restarted = subject.restart_session(requested, "reiniciar").session
    assert restarted.approval_decisions == () and restarted.approval_grants == ()


def test_help_preserves_approvals():
    requested = request_turn().session
    response = DiagnosticConversationEngine().continue_conversation(requested, "ajuda")
    assert response.session is requested and response.session.approval_requests == requested.approval_requests


@pytest.mark.parametrize("ttl", [1, 30, 300])
def test_valid_ttl_is_forwarded(ttl):
    request = request_turn(ttl_seconds=ttl).session.approval_requests[0]
    assert request.expires_at_monotonic == 10 + ttl


def test_expired_request_decision_fails_without_breaking_session():
    subject = DiagnosticSessionEngine(); requested = request_turn(subject, ttl_seconds=1).session
    result = subject.decide_action_approval(requested, requested.approval_requests[0].approval_id, ApprovalStatus.APPROVED, actor(), 11)
    assert not result.session.approval_result.success and result.session.status == requested.status


@pytest.mark.parametrize(
    ("risk", "actor_type", "success"),
    [
        (ExecutionRisk.MEDIUM, ApprovalType.USER_CONFIRMATION, True),
        (ExecutionRisk.MEDIUM, ApprovalType.HUMAN_TECHNICIAN, True),
        (ExecutionRisk.MEDIUM, ApprovalType.ADMINISTRATOR, True),
        (ExecutionRisk.HIGH, ApprovalType.USER_CONFIRMATION, False),
    ],
)
def test_actor_authority_in_session_flow(risk, actor_type, success):
    source = session(action(risk=risk)); subject = DiagnosticSessionEngine(); requested = request_turn(subject, source).session
    result = subject.decide_action_approval(requested, requested.approval_requests[0].approval_id, ApprovalStatus.APPROVED, actor(actor_type), 11)
    assert result.session.approval_result.success is success


@pytest.mark.parametrize("operation", ["request", "decision", "grant", "consume"])
def test_approval_failure_preserves_valid_session(operation):
    subject = DiagnosticSessionEngine(); source = session()
    if operation == "request": turn = subject.request_action_approval(source, "missing")
    elif operation == "decision": turn = subject.decide_action_approval(source, "missing", ApprovalStatus.APPROVED, actor(), 1)
    elif operation == "grant": turn = subject.create_action_grant(source, "missing", 1)
    else: turn = subject.consume_action_grant(source, "missing", "missing", 1)
    assert turn.session.status == source.status and not turn.session.approval_result.success


class RaisingApprovalEngine:
    policy = DiagnosticApprovalPolicy()

    def create_request(self, *args, **kwargs):
        raise RuntimeError("unexpected")


def test_unexpected_approval_exception_is_captured():
    subject = DiagnosticSessionEngine(approval_engine=RaisingApprovalEngine())
    result = subject.request_action_approval(session(), "action-1")
    assert "RuntimeError" in result.session.approval_result.errors[0]


def test_approval_errors_are_added_to_metadata():
    result = DiagnosticSessionEngine().request_action_approval(session(), "missing")
    assert result.session.metadata["approval_errors"]


def test_approval_errors_are_deduplicated():
    subject = DiagnosticSessionEngine(); first = subject.request_action_approval(session(), "missing").session
    second = subject.request_action_approval(first, "missing").session
    assert len(second.metadata["approval_errors"]) == 1


def test_no_action_becomes_running_or_success():
    subject, granted, grant = granted_session(); consumed = subject.consume_action_grant(granted, grant.grant_id, grant.action_id, 13).session
    assert all(item.status not in {ExecutionStatus.RUNNING, ExecutionStatus.SUCCESS} for item in consumed.execution_plan.actions)


def test_default_constructor_builds_approval_engine():
    assert isinstance(DiagnosticSessionEngine().approval_engine, DiagnosticApprovalEngine)


def test_custom_approval_engine_injection():
    approval = DiagnosticApprovalEngine(DiagnosticApprovalPolicy(require_approval_for_low_risk=True))
    assert DiagnosticSessionEngine(approval_engine=approval).approval_engine is approval


def test_custom_approval_policy_is_used():
    approval = DiagnosticApprovalEngine(DiagnosticApprovalPolicy(require_approval_for_low_risk=True))
    result = request_turn(DiagnosticSessionEngine(approval_engine=approval), session(action(risk=ExecutionRisk.LOW)))
    assert result.session.approval_result.success


def test_flow_is_deterministic():
    first = request_turn().session
    second = request_turn().session
    assert first.approval_requests == second.approval_requests


def test_public_imports_remain_available():
    from app.services.diagnostic_engine import DiagnosticSessionEngine as PublicSessionEngine
    assert PublicSessionEngine is DiagnosticSessionEngine


def test_integration_has_no_external_action_imports():
    root = Path(__file__).resolve().parents[3]
    tree = ast.parse((root / "app/services/diagnostic_engine/session_engine.py").read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not imports & {"subprocess", "socket", "requests", "threading", "asyncio"}


def test_sprint_files_are_utf8_without_bom():
    root = Path(__file__).resolve().parents[3]
    for path in (
        root / "app/services/diagnostic_engine/session_models.py",
        root / "app/services/diagnostic_engine/session_engine.py",
        Path(__file__),
    ):
        content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
