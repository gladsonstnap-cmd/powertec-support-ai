import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import DiagnosticExecutorEngine
from app.services.diagnostic_engine.approval_models import ApprovalActor, ApprovalType, ApprovedActionGrant
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction, ExecutionPlan, ExecutionRisk, ExecutionStatus, ExecutionTarget,
)
from app.services.diagnostic_engine.executor_models import AuditEventType, ExecutorBlockReason, ExecutorStatus
from app.services.diagnostic_engine.executor_policy import DiagnosticExecutorPolicy


HERE = Path(__file__).resolve()
ENGINE = HERE.parents[3] / "app" / "services" / "diagnostic_engine" / "executor_engine.py"
PACKAGE = ENGINE.with_name("__init__.py")


def action(**changes):
    values = dict(
        action_id="action-1", action_name="inspect", title="Inspect", description="Read state.",
        target=ExecutionTarget.WINDOWS, status=ExecutionStatus.READY, risk=ExecutionRisk.LOW,
        parameters=(), timeout_seconds=30, requires_confirmation=False, requires_human=False,
        metadata={"action_kind": "read_only", "safe_label": "inspection"},
    )
    values.update(changes)
    return ExecutionAction(**values)


def plan(snapshot=None, **changes):
    values = dict(plan_id="plan-1", status=ExecutionStatus.READY, actions=(snapshot or action(),))
    values.update(changes)
    return ExecutionPlan(**values)


def grant(snapshot=None, **changes):
    snapshot = snapshot or action()
    values = dict(
        grant_id="grant-1", approval_id="approval-1", execution_plan_id="plan-1",
        action_id=snapshot.action_id, action_snapshot=snapshot,
        approved_by=ApprovalActor("actor-1", ApprovalType.HUMAN_TECHNICIAN),
        approved_at_monotonic=1.0, expires_at_monotonic=100.0,
        metadata={"session_id": "session-1"},
    )
    values.update(changes)
    return ApprovedActionGrant(**values)


def built(*, engine=None, snapshot=None, grant_item=None, plan_item=None, now=10.0, **changes):
    snapshot = snapshot or action()
    return (engine or DiagnosticExecutorEngine()).build_request(
        session_id=changes.pop("session_id", "session-1"), diagnostic_plan_id="diagnostic-1",
        execution_plan=plan_item or plan(snapshot), action=snapshot,
        grant=grant_item or grant(snapshot), now_monotonic=now, **changes,
    )


def reason(result):
    return result.attempt.block_reason if result.attempt else None


def test_default_constructor():
    assert DiagnosticExecutorEngine().policy == DiagnosticExecutorPolicy()


def test_custom_policy():
    policy = replace(DiagnosticExecutorPolicy(), allow_medium_risk=True)
    assert DiagnosticExecutorEngine(policy).policy is policy


@pytest.mark.parametrize("session", ["", " ", None])
def test_empty_session_is_invalid(session):
    assert built(session_id=session).success is False


@pytest.mark.parametrize("now", [-1, -0.1, True, "10", None])
def test_invalid_clock_is_rejected(now):
    assert built(now=now).success is False


@pytest.mark.parametrize("dry_run", [None, 0, 1, "true", (), []])
def test_invalid_dry_run_is_rejected(dry_run):
    assert reason(built(dry_run=dry_run)) == ExecutorBlockReason.INVALID_PARAMETERS


def test_valid_build_is_pending_and_deterministic():
    first = built(); second = built()
    assert first == second
    assert first.request.request_id == "executor-plan-1-action-1-grant-1"
    assert first.attempt.status == ExecutorStatus.PENDING
    assert first.success is False


def test_action_outside_plan():
    selected = action(action_id="other")
    assert reason(built(snapshot=selected, plan_item=plan(action()))) == ExecutorBlockReason.ACTION_MISMATCH


@pytest.mark.parametrize(
    ("change", "expected"),
    [("action_id", ExecutorBlockReason.ACTION_MISMATCH), ("execution_plan_id", ExecutorBlockReason.PLAN_MISMATCH)],
)
def test_grant_correlations(change, expected):
    snapshot = action()
    item = grant(snapshot)
    object.__setattr__(item, change, "other")
    assert reason(built(snapshot=snapshot, grant_item=item)) == expected


def test_snapshot_mismatch():
    selected = action()
    item = grant(selected)
    object.__setattr__(item, "action_snapshot", action(title="Changed"))
    assert reason(built(snapshot=selected, grant_item=item)) == ExecutorBlockReason.ACTION_MISMATCH


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"expires_at_monotonic": 10.0}, ExecutorBlockReason.EXPIRED_GRANT),
        ({"expires_at_monotonic": 9.0}, ExecutorBlockReason.EXPIRED_GRANT),
        ({"used": True}, ExecutorBlockReason.USED_GRANT),
        ({"single_use": False}, None),
    ],
)
def test_grant_lifecycle(changes, expected):
    result = built(grant_item=grant(action(), **changes))
    assert reason(result) == expected


@pytest.mark.parametrize(
    ("target", "flag", "allowed"),
    [
        (ExecutionTarget.WINDOWS, "allow_windows_target", True),
        (ExecutionTarget.NETWORK, "allow_network_target", True),
        (ExecutionTarget.LINUX, "allow_linux_target", False),
        (ExecutionTarget.REMOTE_AGENT, "allow_remote_agent_target", False),
        (ExecutionTarget.UNKNOWN, "allow_unknown_target", False),
    ],
)
def test_default_targets(target, flag, allowed):
    snapshot = action(target=target)
    result = built(snapshot=snapshot)
    assert (result.attempt.status == ExecutorStatus.PENDING) is allowed
    if not allowed:
        assert reason(result) == ExecutorBlockReason.TARGET_BLOCKED


@pytest.mark.parametrize(
    ("target", "flag"),
    [
        (ExecutionTarget.WINDOWS, "allow_windows_target"),
        (ExecutionTarget.NETWORK, "allow_network_target"),
        (ExecutionTarget.LINUX, "allow_linux_target"),
        (ExecutionTarget.REMOTE_AGENT, "allow_remote_agent_target"),
        (ExecutionTarget.UNKNOWN, "allow_unknown_target"),
    ],
)
def test_each_target_can_be_explicitly_blocked(target, flag):
    engine = DiagnosticExecutorEngine(replace(DiagnosticExecutorPolicy(), **{flag: False}))
    assert reason(built(engine=engine, snapshot=action(target=target))) == ExecutorBlockReason.TARGET_BLOCKED


@pytest.mark.parametrize(
    ("risk", "allowed"),
    [(ExecutionRisk.LOW, True), (ExecutionRisk.MEDIUM, False), (ExecutionRisk.HIGH, False), (ExecutionRisk.CRITICAL, False)],
)
def test_default_risk_policy(risk, allowed):
    result = built(snapshot=action(risk=risk))
    assert (result.attempt.status == ExecutorStatus.PENDING) is allowed
    if not allowed:
        assert reason(result) == ExecutorBlockReason.RISK_BLOCKED


@pytest.mark.parametrize(
    ("risk", "flag"),
    [
        (ExecutionRisk.LOW, "allow_low_risk"), (ExecutionRisk.MEDIUM, "allow_medium_risk"),
        (ExecutionRisk.HIGH, "allow_high_risk"), (ExecutionRisk.CRITICAL, "allow_critical_risk"),
    ],
)
def test_each_risk_can_be_explicitly_allowed(risk, flag):
    engine = DiagnosticExecutorEngine(replace(DiagnosticExecutorPolicy(), **{flag: True}))
    assert built(engine=engine, snapshot=action(risk=risk)).attempt.status == ExecutorStatus.PENDING


@pytest.mark.parametrize(
    ("kind", "allowed", "expected"),
    [
        ("read_only", True, None), ("state_changing", False, ExecutorBlockReason.POLICY_BLOCKED),
        ("destructive", False, ExecutorBlockReason.DESTRUCTIVE_ACTION),
        ("unknown", False, ExecutorBlockReason.POLICY_BLOCKED),
    ],
)
def test_action_kinds(kind, allowed, expected):
    result = built(snapshot=action(metadata={"action_kind": kind}))
    assert (result.attempt.status == ExecutorStatus.PENDING) is allowed
    assert reason(result) == expected


@pytest.mark.parametrize("metadata", [{}, {"action_kind": None}, {"action_kind": 1}])
def test_unclassified_action_is_conservatively_blocked(metadata):
    assert reason(built(snapshot=action(metadata=metadata))) == ExecutorBlockReason.POLICY_BLOCKED


@pytest.mark.parametrize("timeout", [1, 10, 30, 299, 300])
def test_valid_custom_timeouts(timeout):
    assert built(timeout_seconds=timeout).request.timeout_seconds == timeout


@pytest.mark.parametrize("timeout", [0, -1, 301, True, 1.5, "30"])
def test_invalid_timeouts(timeout):
    assert reason(built(timeout_seconds=timeout)) == ExecutorBlockReason.INVALID_PARAMETERS


def test_default_timeout():
    assert built().request.timeout_seconds == DiagnosticExecutorPolicy().default_timeout_seconds


def test_required_dry_run():
    policy = replace(DiagnosticExecutorPolicy(), allow_medium_risk=True)
    result = built(engine=DiagnosticExecutorEngine(policy), snapshot=action(risk=ExecutionRisk.MEDIUM), dry_run=False)
    assert reason(result) == ExecutorBlockReason.POLICY_BLOCKED


def test_low_risk_build_may_be_non_dry_run_but_simulate_rejects_it():
    result = built(dry_run=False)
    assert result.request is not None
    simulated = DiagnosticExecutorEngine().simulate(result.request, 11.0)
    assert simulated.attempt.status == ExecutorStatus.BLOCKED
    assert simulated.attempt.block_reason == ExecutorBlockReason.POLICY_BLOCKED


def test_validate_valid_request_is_authorized_without_execution_events():
    request = built().request
    result = DiagnosticExecutorEngine().validate_request(request, 11.0)
    types = tuple(event.event_type for event in result.audit_events)
    assert result.success is False and result.attempt.status == ExecutorStatus.AUTHORIZED
    assert types == (
        AuditEventType.EXECUTION_REQUESTED, AuditEventType.VALIDATION_STARTED,
        AuditEventType.VALIDATION_PASSED, AuditEventType.AUTHORIZATION_CHECKED,
        AuditEventType.AUTHORIZATION_ACCEPTED,
    )
    assert AuditEventType.EXECUTION_STARTED not in types


@pytest.mark.parametrize(
    ("attribute", "value", "expected"),
    [
        ("grant_id", "other", ExecutorBlockReason.INVALID_GRANT),
        ("approval_id", "other", ExecutorBlockReason.INVALID_GRANT),
        ("action_id", "other", ExecutorBlockReason.ACTION_MISMATCH),
        ("execution_plan_id", "other", ExecutorBlockReason.PLAN_MISMATCH),
    ],
)
def test_validate_detects_tampered_grant(attribute, value, expected):
    request = deepcopy(built().request)
    object.__setattr__(request.grant_snapshot, attribute, value)
    result = DiagnosticExecutorEngine().validate_request(request, 11.0)
    assert reason(result) == expected
    assert AuditEventType.AUTHORIZATION_REJECTED in tuple(e.event_type for e in result.audit_events)


@pytest.mark.parametrize("metadata", [{}, {"session_id": ""}, {"session_id": "other"}])
def test_missing_or_different_session_binding_is_blocked(metadata):
    result = built(grant_item=grant(action(), metadata=metadata))
    assert reason(result) == ExecutorBlockReason.SESSION_MISMATCH


def test_session_policy_can_disable_binding_requirement():
    engine = DiagnosticExecutorEngine(replace(DiagnosticExecutorPolicy(), require_session_match=False))
    assert built(engine=engine, grant_item=grant(action(), metadata={})).attempt.status == ExecutorStatus.PENDING


def test_simulate_is_structural_success_with_exact_contract():
    request = built().request
    result = DiagnosticExecutorEngine().simulate(request, 12.0)
    assert result.success and result.attempt.status == ExecutorStatus.SUCCESS
    assert result.attempt.started_at_monotonic == result.attempt.finished_at_monotonic == 12.0
    assert result.attempt.exit_code == 0
    assert result.attempt.output_summary == "Dry-run estrutural concluído; nenhuma ação foi executada."
    assert result.attempt.error_summary is None and result.attempt.block_reason is None


def test_simulate_event_sequence_and_messages():
    result = DiagnosticExecutorEngine().simulate(built().request, 12.0)
    assert tuple(event.event_type for event in result.audit_events) == (
        AuditEventType.EXECUTION_REQUESTED, AuditEventType.VALIDATION_STARTED,
        AuditEventType.VALIDATION_PASSED, AuditEventType.AUTHORIZATION_CHECKED,
        AuditEventType.AUTHORIZATION_ACCEPTED, AuditEventType.EXECUTION_STARTED,
        AuditEventType.EXECUTION_SUCCEEDED,
    )
    assert result.audit_events[-2].message == "Dry-run estrutural iniciado; nenhuma ação foi executada."
    assert result.audit_events[-1].message == "Dry-run estrutural concluído; nenhuma alteração foi realizada."


@pytest.mark.parametrize("operation", ["build", "validate", "simulate"])
def test_inputs_are_preserved(operation):
    snapshot = action(); item_plan = plan(snapshot); item_grant = grant(snapshot)
    originals = deepcopy((snapshot, item_plan, item_grant))
    result = built(snapshot=snapshot, plan_item=item_plan, grant_item=item_grant)
    if operation == "validate":
        DiagnosticExecutorEngine().validate_request(result.request, 11.0)
    if operation == "simulate":
        DiagnosticExecutorEngine().simulate(result.request, 11.0)
    assert (snapshot, item_plan, item_grant) == originals
    assert item_grant.used is False and snapshot.status == ExecutionStatus.READY


@pytest.mark.parametrize("operation", ["build", "validate", "simulate"])
def test_attempt_id_is_deterministic_and_no_retry(operation):
    result = built()
    if operation == "validate": result = DiagnosticExecutorEngine().validate_request(result.request, 11.0)
    if operation == "simulate": result = DiagnosticExecutorEngine().simulate(result.request, 11.0)
    assert result.attempt.attempt_id == "attempt-executor-plan-1-action-1-grant-1-001"
    assert result.attempt.attempt_number == 1


@pytest.mark.parametrize("limit", [1, 2, 3, 4, 5, 6, 7])
def test_audit_limit(limit):
    engine = DiagnosticExecutorEngine(replace(DiagnosticExecutorPolicy(), max_audit_events_per_request=limit))
    result = engine.simulate(built(engine=engine).request, 11.0)
    assert len(result.audit_events) == limit
    assert tuple(e.event_id for e in result.audit_events) == tuple(
        f"audit-executor-plan-1-action-1-grant-1-{index:03d}" for index in range(1, limit + 1)
    )


def test_audit_can_be_disabled():
    engine = DiagnosticExecutorEngine(replace(DiagnosticExecutorPolicy(), require_audit_trail=False))
    assert engine.simulate(built(engine=engine).request, 11.0).audit_events == ()


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_reasoning_limit(limit):
    engine = DiagnosticExecutorEngine(replace(DiagnosticExecutorPolicy(), max_reasoning_messages=limit))
    assert len(engine.validate_request(built(engine=engine).request, 11.0).reasoning) <= limit


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_error_limit(limit):
    engine = DiagnosticExecutorEngine(replace(DiagnosticExecutorPolicy(), max_errors=limit))
    assert len(engine.build_request("", None, plan(), action(), grant(), 1.0).errors) <= limit


def test_metadata_is_copied_and_safe():
    result = built()
    assert result.request.metadata == {"action_kind": "read_only", "safe_label": "inspection"}
    assert result.request.metadata is not result.request.action_snapshot.metadata


@pytest.mark.parametrize("key", ["password", "token", "secret", "authorization", "api_key"])
def test_sensitive_metadata_is_rejected_as_domain_failure(key):
    result = built(snapshot=action(metadata={"action_kind": "read_only", key: "hidden"}))
    assert result.success is False and reason(result) == ExecutorBlockReason.INVALID_PARAMETERS


def test_descriptive_rollback_only_with_explicit_information():
    policy = replace(DiagnosticExecutorPolicy(), allow_state_changing_actions=True, allow_rollback=True)
    engine = DiagnosticExecutorEngine(policy)
    metadata = {
        "action_kind": "state_changing", "rollback_description": "Restore prior state.",
        "rollback_action_name": "restore_prior_state",
    }
    result = engine.validate_request(built(engine=engine, snapshot=action(metadata=metadata)).request, 11.0)
    assert result.rollback_plan is not None and result.rollback_plan.supported
    assert result.attempt.status == ExecutorStatus.AUTHORIZED


@pytest.mark.parametrize("metadata", [
    {"action_kind": "state_changing"},
    {"action_kind": "state_changing", "rollback_description": "Restore."},
    {"action_kind": "read_only"},
])
def test_rollback_is_never_invented(metadata):
    policy = replace(DiagnosticExecutorPolicy(), allow_state_changing_actions=True, allow_rollback=True)
    engine = DiagnosticExecutorEngine(policy)
    result = engine.validate_request(built(engine=engine, snapshot=action(metadata=metadata)).request, 11.0)
    assert result.rollback_plan is None


def test_build_audit_trail_is_pure():
    engine = DiagnosticExecutorEngine(); result = engine.simulate(built().request, 11.0)
    trail = engine.build_audit_trail("session-1", "plan-1", result.audit_events, (result.attempt,))
    assert trail.events == result.audit_events and trail.attempts == (result.attempt,)


@pytest.mark.parametrize("name", ["subprocess", "os", "socket", "requests", "httpx"])
def test_no_dangerous_imports(name):
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


def test_public_import():
    from app.services.diagnostic_engine import DiagnosticExecutorEngine as PublicEngine
    assert PublicEngine is DiagnosticExecutorEngine


@pytest.mark.parametrize("path", [ENGINE, PACKAGE, HERE])
def test_utf8_without_bom(path):
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    raw.decode("utf-8")
