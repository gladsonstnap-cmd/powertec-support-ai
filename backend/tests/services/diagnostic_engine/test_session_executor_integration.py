import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import DiagnosticExecutorEngine, DiagnosticSessionEngine
from app.services.diagnostic_engine.approval_models import ApprovalActor, ApprovalType, ApprovedActionGrant
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction, ExecutionPlan, ExecutionResult, ExecutionRisk, ExecutionStatus, ExecutionTarget,
)
from app.services.diagnostic_engine.executor_models import ExecutorBlockReason, ExecutorResult, ExecutorStatus
from app.services.diagnostic_engine.executor_policy import DiagnosticExecutorPolicy
from app.services.diagnostic_engine.session_models import DiagnosticSession, DiagnosticSessionStatus


ROOT = Path(__file__).resolve().parents[3]


def action(**changes):
    values = dict(
        action_id="action-1", action_name="inspect", title="Inspect", description="Read only.",
        target=ExecutionTarget.WINDOWS, status=ExecutionStatus.READY, risk=ExecutionRisk.LOW,
        parameters=(), timeout_seconds=30, requires_confirmation=False, requires_human=False,
        metadata={"action_kind": "read_only"},
    )
    values.update(changes)
    return ExecutionAction(**values)


def plan(item=None):
    item = item or action()
    return ExecutionPlan("plan-1", ExecutionStatus.READY, (item,), item.action_id)


def grant(item=None, **changes):
    item = item or action()
    values = dict(
        grant_id="grant-1", approval_id="approval-1", execution_plan_id="plan-1",
        action_id=item.action_id, action_snapshot=item,
        approved_by=ApprovalActor("actor-1", ApprovalType.HUMAN_TECHNICIAN),
        approved_at_monotonic=1.0, expires_at_monotonic=100.0,
        metadata={"session_id": "session-1"},
    )
    values.update(changes)
    return ApprovedActionGrant(**values)


def session(item=None, grant_item=None, **changes):
    item = item or action(); source_plan = plan(item)
    values = dict(
        session_id="session-1", status=DiagnosticSessionStatus.READY_FOR_ACTION,
        original_message="Erro", last_message="Erro", execution_plan=source_plan,
        execution_result=ExecutionResult(True, source_plan, item),
        approval_grants=(grant_item or grant(item),),
    )
    values.update(changes)
    return DiagnosticSession(**values)


def build(subject=None, source=None, **changes):
    return (subject or DiagnosticSessionEngine()).build_executor_request(
        source or session(), "action-1", "grant-1", 10.0, **changes,
    )


def built(subject=None, source=None, **changes):
    subject = subject or DiagnosticSessionEngine()
    return subject, build(subject, source, **changes).session


def test_session_executor_defaults_are_empty():
    source = DiagnosticSession("id", DiagnosticSessionStatus.NEW, "erro", "erro")
    assert source.executor_requests == () and source.execution_attempts == ()
    assert source.executor_results == () and source.execution_audit_trails == ()
    assert source.current_executor_result is None


def test_default_constructor_builds_executor_engine():
    assert isinstance(DiagnosticSessionEngine().executor_engine, DiagnosticExecutorEngine)


def test_start_session_does_not_create_executor_request():
    started = DiagnosticSessionEngine().start_session("Erro de rede", session_id="session-1").session
    assert started.executor_requests == () and started.current_executor_result is None


def test_continue_session_does_not_create_executor_request_automatically():
    subject = DiagnosticSessionEngine()
    started = subject.start_session("Erro de rede", session_id="session-1").session
    continued = subject.continue_session(started, "O cabo está conectado").session
    assert continued.executor_requests == () and continued.executor_results == ()


def test_custom_executor_engine_injection():
    executor = DiagnosticExecutorEngine()
    assert DiagnosticSessionEngine(executor_engine=executor).executor_engine is executor


def test_build_valid_request_records_all_structural_outputs():
    turn = build()
    assert len(turn.session.executor_requests) == 1
    assert len(turn.session.execution_attempts) == 1
    assert len(turn.session.executor_results) == 1
    assert len(turn.session.execution_audit_trails) == 1
    assert turn.session.current_executor_result == turn.session.executor_results[-1]


@pytest.mark.parametrize("action_id", ["missing", "", None])
def test_missing_action_is_controlled(action_id):
    turn = DiagnosticSessionEngine().build_executor_request(session(), action_id, "grant-1", 10)
    assert turn.session.status == DiagnosticSessionStatus.READY_FOR_ACTION
    assert turn.session.current_executor_result.success is False
    assert turn.session.metadata["executor_errors"]


@pytest.mark.parametrize("grant_id", ["missing", "", None])
def test_missing_grant_is_controlled(grant_id):
    turn = DiagnosticSessionEngine().build_executor_request(session(), "action-1", grant_id, 10)
    assert turn.session.current_executor_result.success is False


def test_missing_execution_plan_is_controlled():
    turn = DiagnosticSessionEngine().build_executor_request(
        session(execution_plan=None, execution_result=None), "action-1", "grant-1", 10,
    )
    assert turn.session.metadata["executor_errors"]


def test_grant_from_old_plan_is_rejected():
    old = grant(); object.__setattr__(old, "execution_plan_id", "old-plan")
    turn = build(source=session(grant_item=old))
    assert turn.session.executor_requests == ()


def test_duplicate_equivalent_request_is_not_added():
    subject, first = built(); second = build(subject, first).session
    assert second.executor_requests == first.executor_requests
    assert second.executor_results == first.executor_results


@pytest.mark.parametrize("change", [{}, {"dry_run": False}, {"timeout_seconds": 10}])
def test_request_equivalence_key(change):
    subject, first = built(); second = build(subject, first, **change).session
    expected = 1 if not change else 2
    assert len(second.executor_requests) == expected


def test_validate_records_authorized_result_attempt_and_trail():
    subject, source = built(); request = source.executor_requests[0]
    updated = subject.validate_executor_request(source, request.request_id, 11).session
    assert updated.current_executor_result.attempt.status == ExecutorStatus.AUTHORIZED
    assert len(updated.executor_results) == 2 and len(updated.execution_attempts) == 2
    assert len(updated.execution_audit_trails) == 2


def test_simulate_records_structural_success():
    subject, source = built(); request = source.executor_requests[0]
    updated = subject.simulate_executor_request(source, request.request_id, 12).session
    assert updated.current_executor_result.success
    assert updated.current_executor_result.attempt.status == ExecutorStatus.SUCCESS
    assert len(updated.executor_results) == 2


@pytest.mark.parametrize("operation", ["validate", "simulate"])
def test_missing_request_is_controlled(operation):
    subject = DiagnosticSessionEngine()
    method = getattr(subject, f"{operation}_executor_request")
    turn = method(session(), "missing", 11)
    assert turn.session.current_executor_result.success is False
    assert turn.session.metadata["executor_errors"]


def test_simulate_rejects_non_dry_run():
    subject, source = built(dry_run=False); request = source.executor_requests[0]
    updated = subject.simulate_executor_request(source, request.request_id, 11).session
    assert updated.current_executor_result.attempt.status == ExecutorStatus.BLOCKED
    assert updated.current_executor_result.attempt.block_reason == ExecutorBlockReason.POLICY_BLOCKED


@pytest.mark.parametrize("operation", ["build", "validate", "simulate"])
def test_grant_is_never_consumed(operation):
    subject = DiagnosticSessionEngine(); source = session(); original = deepcopy(source.approval_grants)
    created = build(subject, source).session
    if operation == "validate":
        created = subject.validate_executor_request(created, created.executor_requests[0].request_id, 11).session
    if operation == "simulate":
        created = subject.simulate_executor_request(created, created.executor_requests[0].request_id, 11).session
    assert created.approval_grants == original and all(not item.used for item in created.approval_grants)


@pytest.mark.parametrize("operation", ["build", "validate", "simulate"])
def test_action_and_plan_are_never_changed(operation):
    subject = DiagnosticSessionEngine(); source = session(); original = deepcopy(source.execution_plan)
    created = build(subject, source).session
    if operation == "validate":
        created = subject.validate_executor_request(created, created.executor_requests[0].request_id, 11).session
    if operation == "simulate":
        created = subject.simulate_executor_request(created, created.executor_requests[0].request_id, 11).session
    assert created.execution_plan == original
    assert all(item.status not in {ExecutionStatus.RUNNING, ExecutionStatus.SUCCESS} for item in created.execution_plan.actions)


@pytest.mark.parametrize("operation", ["build", "validate", "simulate"])
def test_previous_session_is_immutable(operation):
    subject = DiagnosticSessionEngine(); source = session(); before = deepcopy(source)
    created = build(subject, source).session
    if operation == "validate": subject.validate_executor_request(created, created.executor_requests[0].request_id, 11)
    if operation == "simulate": subject.simulate_executor_request(created, created.executor_requests[0].request_id, 11)
    assert source == before


@pytest.mark.parametrize("field", [
    "approval_grants", "approval_requests", "approval_decisions", "execution_plan",
    "diagnostic_plan", "memory_snapshot", "planner_result", "execution_result",
])
def test_diagnostic_history_is_preserved(field):
    source = session(); before = deepcopy(getattr(source, field)); build(source=source)
    assert getattr(source, field) == before


@pytest.mark.parametrize("field", [
    "executor_requests", "execution_attempts", "executor_results", "execution_audit_trails",
])
def test_session_model_defensively_copies_executor_collections(field):
    _, source = built(); items = list(getattr(source, field)); copied = replace(source, **{field: items})
    items.clear()
    assert getattr(copied, field) == getattr(source, field)
    assert getattr(copied, field) is not getattr(source, field)


def test_audit_events_are_ordered():
    subject, source = built(); request = source.executor_requests[0]
    simulated = subject.simulate_executor_request(source, request.request_id, 12).session
    events = simulated.execution_audit_trails[-1].events
    assert events == tuple(sorted(events, key=lambda item: (item.occurred_at_monotonic, item.event_id)))


@pytest.mark.parametrize("command", ["status", "cancelar", "humano"])
def test_session_commands_preserve_executor_history(command):
    subject, source = built(); updated = subject.continue_session(source, command).session
    assert updated.executor_requests == source.executor_requests
    assert updated.executor_results == source.executor_results


def test_restart_starts_with_empty_executor_history():
    subject, source = built(); restarted = subject.restart_session(source, "reiniciar").session
    assert restarted.executor_requests == () and restarted.execution_attempts == ()
    assert restarted.executor_results == () and restarted.execution_audit_trails == ()
    assert restarted.current_executor_result is None


@pytest.mark.parametrize("method", ["build_request", "validate_request", "simulate"])
def test_unexpected_executor_exception_is_captured(method):
    class RaisingExecutor(DiagnosticExecutorEngine):
        def __getattribute__(self, name):
            if name == method:
                def fail(*args, **kwargs): raise RuntimeError("unexpected")
                return fail
            return super().__getattribute__(name)

    subject = DiagnosticSessionEngine(executor_engine=RaisingExecutor())
    source = session()
    if method == "build_request": result = build(subject, source).session
    else:
        prepared = DiagnosticSessionEngine().build_executor_request(source, "action-1", "grant-1", 10).session
        operation = subject.validate_executor_request if method == "validate_request" else subject.simulate_executor_request
        result = operation(prepared, prepared.executor_requests[0].request_id, 11).session
    assert "RuntimeError" in result.metadata["executor_errors"][-1]
    assert result.status == source.status


def test_executor_errors_are_deduplicated():
    subject = DiagnosticSessionEngine()
    source = subject.build_executor_request(session(), "missing", "grant-1", 10).session
    second = subject.build_executor_request(source, "missing", "grant-1", 10).session
    assert len(second.metadata["executor_errors"]) == 1


@pytest.mark.parametrize("metadata", [{}, {"session_id": "other"}])
def test_session_match_is_conservative(metadata):
    item = action(); source = session(item, grant(item, metadata=metadata))
    assert build(source=source).session.current_executor_result.attempt.block_reason == ExecutorBlockReason.SESSION_MISMATCH


def test_custom_policy_can_disable_session_match():
    item = action(); source = session(item, grant(item, metadata={}))
    policy = replace(DiagnosticExecutorPolicy(), require_session_match=False)
    result = build(DiagnosticSessionEngine(executor_engine=DiagnosticExecutorEngine(policy)), source).session
    assert result.executor_requests


@pytest.mark.parametrize(
    ("item", "reason"),
    [
        (action(target=ExecutionTarget.LINUX), ExecutorBlockReason.TARGET_BLOCKED),
        (action(risk=ExecutionRisk.MEDIUM), ExecutorBlockReason.RISK_BLOCKED),
    ],
)
def test_policy_block_is_stored_without_breaking_session(item, reason):
    source = session(item, grant(item)); result = build(source=source).session
    assert result.current_executor_result.attempt.block_reason == reason
    assert result.status == source.status


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"expires_at_monotonic": 10.0}, ExecutorBlockReason.EXPIRED_GRANT),
        ({"used": True}, ExecutorBlockReason.USED_GRANT),
    ],
)
def test_invalid_grant_state_is_stored(changes, reason):
    item = action(); source = session(item, grant(item, **changes)); result = build(source=source).session
    assert result.current_executor_result.attempt.block_reason == reason


def test_same_input_is_deterministic():
    assert build().session == build().session


def test_public_imports_remain_available():
    from app.services.diagnostic_engine import DiagnosticSessionEngine as PublicSessionEngine
    assert PublicSessionEngine is DiagnosticSessionEngine


@pytest.mark.parametrize("name", ["subprocess", "socket", "requests", "httpx", "paramiko"])
def test_session_integration_has_no_external_action_imports(name):
    tree = ast.parse((ROOT / "app/services/diagnostic_engine/session_engine.py").read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("path", [
    ROOT / "app/services/diagnostic_engine/session_models.py",
    ROOT / "app/services/diagnostic_engine/session_engine.py",
    Path(__file__),
])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
