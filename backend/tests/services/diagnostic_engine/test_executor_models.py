from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    AuditEvent,
    AuditEventType,
    ExecutionAttempt,
    ExecutionAuditTrail,
    ExecutionContext,
    ExecutorBlockReason,
    ExecutorRequest,
    ExecutorResult,
    ExecutorStatus,
    RollbackPlan,
)
from app.services.diagnostic_engine.approval_models import ApprovalActor, ApprovalType, ApprovedActionGrant
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction, ExecutionParameter, ExecutionRisk, ExecutionStatus, ExecutionTarget,
)


def action(**overrides):
    values = {
        "action_id": "action-1", "action_name": "check_status", "title": "Verificar status",
        "description": "Contrato descritivo.", "target": ExecutionTarget.WINDOWS,
        "status": ExecutionStatus.READY, "risk": ExecutionRisk.MEDIUM, "parameters": (),
        "timeout_seconds": 30, "requires_confirmation": True, "requires_human": False,
    }
    values.update(overrides)
    return ExecutionAction(**values)


def grant(**overrides):
    snapshot = overrides.pop("action_snapshot", action())
    values = {
        "grant_id": "grant-1", "approval_id": "approval-1", "execution_plan_id": "plan-1",
        "action_id": snapshot.action_id, "action_snapshot": snapshot,
        "approved_by": ApprovalActor("actor-1", ApprovalType.HUMAN_TECHNICIAN),
        "approved_at_monotonic": 1.0, "expires_at_monotonic": 100.0,
    }
    values.update(overrides)
    return ApprovedActionGrant(**values)


def context(**overrides):
    values = {
        "session_id": "session-1", "diagnostic_plan_id": "diagnostic-1",
        "execution_plan_id": "plan-1", "action_id": "action-1", "grant_id": "grant-1",
        "approval_id": "approval-1", "target": ExecutionTarget.WINDOWS,
        "risk": ExecutionRisk.MEDIUM, "requested_at_monotonic": 2.0,
    }
    values.update(overrides)
    return ExecutionContext(**values)


def request(**overrides):
    snapshot = overrides.pop("action_snapshot", action())
    values = {
        "request_id": "executor-request-1", "context": context(), "action_snapshot": snapshot,
        "grant_snapshot": grant(action_snapshot=snapshot),
    }
    values.update(overrides)
    return ExecutorRequest(**values)


def event(event_id="event-1", occurred=3.0, **overrides):
    values = {
        "event_id": event_id, "event_type": AuditEventType.EXECUTION_REQUESTED,
        "request_id": "executor-request-1", "session_id": "session-1",
        "execution_plan_id": "plan-1", "action_id": "action-1",
        "occurred_at_monotonic": occurred, "message": "Execução solicitada.",
    }
    values.update(overrides)
    return AuditEvent(**values)


def attempt(**overrides):
    values = {
        "attempt_id": "attempt-1", "request_id": "executor-request-1", "attempt_number": 1,
        "status": ExecutorStatus.PENDING, "audit_events": (event(),),
    }
    values.update(overrides)
    return ExecutionAttempt(**values)


def rollback(**overrides):
    values = {"rollback_id": "rollback-1", "original_action_id": "action-1", "supported": False}
    values.update(overrides)
    return RollbackPlan(**values)


@pytest.mark.parametrize("enum_type", [ExecutorStatus, ExecutorBlockReason, AuditEventType])
def test_enums_are_string_enums(enum_type):
    assert all(isinstance(item, str) and item.name == item.value for item in enum_type)


def test_all_enum_members_are_stable():
    assert [item.name for item in ExecutorStatus] == [
        "PENDING", "VALIDATING", "AUTHORIZED", "BLOCKED", "RUNNING", "SUCCESS", "FAILED",
        "CANCELLED", "TIMED_OUT", "ROLLBACK_PENDING", "ROLLBACK_SUCCESS", "ROLLBACK_FAILED",
    ]
    assert len(ExecutorBlockReason) == 17 and len(AuditEventType) == 17


def test_execution_context_valid():
    assert context().requested_at_monotonic == 2.0


def test_execution_context_allows_no_diagnostic_plan():
    assert context(diagnostic_plan_id=None).diagnostic_plan_id is None


@pytest.mark.parametrize("field", ["session_id", "execution_plan_id", "action_id", "grant_id", "approval_id"])
@pytest.mark.parametrize("invalid", ["", "   ", None])
def test_execution_context_rejects_empty_ids(field, invalid):
    with pytest.raises(ValueError, match=field):
        context(**{field: invalid})


@pytest.mark.parametrize("timestamp", [-1, -0.1, True, "2", None])
def test_execution_context_rejects_invalid_timestamp(timestamp):
    with pytest.raises(ValueError, match="requested_at_monotonic"):
        context(requested_at_monotonic=timestamp)


@pytest.mark.parametrize(("field", "invalid"), [("target", "WINDOWS"), ("risk", "MEDIUM")])
def test_execution_context_rejects_invalid_enum(field, invalid):
    with pytest.raises(ValueError, match=field):
        context(**{field: invalid})


def test_execution_context_metadata_is_defensive():
    metadata = {"nested": [1]}; item = context(metadata=metadata); metadata["nested"].append(2)
    assert item.metadata == {"nested": [1]}


SENSITIVE_KEYS = (
    "password", "senha", "token", "secret", "segredo", "credential", "credencial",
    "api_key", "authorization", "bearer", "cookie", "private_key",
)


@pytest.mark.parametrize("key", SENSITIVE_KEYS)
def test_execution_context_rejects_sensitive_metadata(key):
    with pytest.raises(ValueError, match="metadata"):
        context(metadata={key: "hidden"})


def test_nested_secret_is_rejected():
    with pytest.raises(ValueError, match="metadata"):
        context(metadata={"safe": [{"nested": {"token": "hidden"}}]})


def test_executor_request_valid_and_conservative_defaults():
    item = request()
    assert item.status == ExecutorStatus.PENDING and item.dry_run is True and item.timeout_seconds == 30


@pytest.mark.parametrize("request_id", ["", " ", None])
def test_executor_request_rejects_empty_id(request_id):
    with pytest.raises(ValueError, match="request_id"):
        request(request_id=request_id)


def test_executor_request_rejects_action_context_mismatch():
    with pytest.raises(ValueError, match="action_snapshot.action_id"):
        request(action_snapshot=action(action_id="other"))


@pytest.mark.parametrize(
    ("field", "value"),
    [("action_id", "other"), ("grant_id", "other"), ("approval_id", "other"), ("execution_plan_id", "other")],
)
def test_executor_request_rejects_grant_context_mismatch(field, value):
    with pytest.raises(ValueError, match=field):
        request(grant_snapshot=grant(**{field: value}))


def test_executor_request_rejects_grant_action_snapshot_mismatch():
    divergent = action(title="Outro snapshot")
    with pytest.raises(ValueError, match="action_snapshot"):
        request(grant_snapshot=grant(action_snapshot=divergent, action_id="action-1"))


@pytest.mark.parametrize("timeout", [0, -1, True, 1.5, "30", None])
def test_executor_request_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="timeout_seconds"):
        request(timeout_seconds=timeout)


@pytest.mark.parametrize("dry_run", [0, 1, "true", None])
def test_executor_request_rejects_non_boolean_dry_run(dry_run):
    with pytest.raises(ValueError, match="dry_run"):
        request(dry_run=dry_run)


@pytest.mark.parametrize("status", [item for item in ExecutorStatus if item != ExecutorStatus.SUCCESS])
def test_executor_request_accepts_structural_non_success_statuses(status):
    assert request(status=status).status == status


def test_executor_request_rejects_initial_success():
    with pytest.raises(ValueError, match="SUCCESS"):
        request(status=ExecutorStatus.SUCCESS)


def test_executor_request_snapshot_is_defensive():
    item = request(); assert item.action_snapshot == action() and item.action_snapshot is not item.grant_snapshot.action_snapshot


def test_audit_event_valid():
    assert event().event_type == AuditEventType.EXECUTION_REQUESTED


@pytest.mark.parametrize("field", ["event_id", "request_id", "session_id", "execution_plan_id", "action_id"])
def test_audit_event_rejects_empty_ids(field):
    with pytest.raises(ValueError, match=field):
        event(**{field: ""})


@pytest.mark.parametrize("message", ["", " ", None])
def test_audit_event_rejects_empty_message(message):
    with pytest.raises(ValueError, match="message"):
        event(message=message)


@pytest.mark.parametrize("occurred", [-1, True, "3", None])
def test_audit_event_rejects_invalid_time(occurred):
    with pytest.raises(ValueError, match="occurred_at_monotonic"):
        event(occurred=occurred)


def test_audit_event_converts_errors_to_tuple():
    errors = ["erro"]; item = event(errors=errors); errors.append("outro")
    assert item.errors == ("erro",)


def test_execution_attempt_valid():
    assert attempt().attempt_number == 1


@pytest.mark.parametrize("number", [0, -1, True, 1.5, "1"])
def test_execution_attempt_rejects_invalid_number(number):
    with pytest.raises(ValueError, match="attempt_number"):
        attempt(attempt_number=number)


def test_execution_attempt_rejects_finished_before_started():
    with pytest.raises(ValueError, match="finished_at_monotonic"):
        attempt(started_at_monotonic=10, finished_at_monotonic=9)


def test_blocked_attempt_requires_reason():
    with pytest.raises(ValueError, match="block_reason"):
        attempt(status=ExecutorStatus.BLOCKED)


def test_blocked_attempt_accepts_reason():
    item = attempt(status=ExecutorStatus.BLOCKED, block_reason=ExecutorBlockReason.POLICY_BLOCKED)
    assert item.block_reason == ExecutorBlockReason.POLICY_BLOCKED


def test_success_attempt_rejects_block_reason():
    with pytest.raises(ValueError, match="block_reason"):
        attempt(status=ExecutorStatus.SUCCESS, block_reason=ExecutorBlockReason.UNKNOWN)


def test_attempt_audit_events_are_immutable_tuple():
    events = [event()]; item = attempt(audit_events=events); events.clear()
    assert item.audit_events == (event(),)


def test_rollback_unsupported_is_descriptive_and_empty():
    item = rollback()
    assert item.supported is False and item.rollback_action_name is None and item.parameters == ()


def test_rollback_supported_requires_description():
    with pytest.raises(ValueError, match="description"):
        rollback(supported=True)


def test_rollback_supported_valid():
    item = rollback(supported=True, description="Restaurar configuração anterior.", rollback_action_name="restore_config")
    assert item.supported and item.description


@pytest.mark.parametrize("field", ["supported", "requires_confirmation", "requires_human"])
def test_rollback_rejects_non_boolean_flags(field):
    with pytest.raises(ValueError, match=field):
        rollback(**{field: 1})


def test_rollback_parameters_are_defensive_tuple():
    parameter = ExecutionParameter("path", "safe", True, "Caminho")
    parameters = [parameter]; item = rollback(parameters=parameters); parameters.clear()
    assert item.parameters == (parameter,)


def test_executor_result_success_valid():
    successful = attempt(status=ExecutorStatus.SUCCESS)
    assert ExecutorResult(True, request(), successful).success


@pytest.mark.parametrize("missing", ["request", "attempt"])
def test_executor_result_success_requires_request_and_attempt(missing):
    values = {"request": request(), "attempt": attempt(status=ExecutorStatus.SUCCESS)}; values[missing] = None
    with pytest.raises(ValueError, match="requires"):
        ExecutorResult(success=True, **values)


def test_executor_result_success_requires_success_attempt():
    with pytest.raises(ValueError, match="SUCCESS"):
        ExecutorResult(True, request(), attempt())


def test_executor_result_rejects_request_id_mismatch():
    with pytest.raises(ValueError, match="request_id"):
        ExecutorResult(request=request(), attempt=attempt(request_id="other"))


def test_executor_result_rejects_duplicate_audit_event():
    with pytest.raises(ValueError, match="event_id"):
        ExecutorResult(audit_events=(event(), event()))


def test_executor_result_collections_are_defensive():
    reasoning = ["seguro"]; errors = ["erro"]; item = ExecutorResult(reasoning=reasoning, errors=errors)
    reasoning.append("outro"); errors.append("outro")
    assert item.reasoning == ("seguro",) and item.errors == ("erro",)


def test_execution_audit_trail_valid():
    trail = ExecutionAuditTrail("session-1", "plan-1", (event(),), (attempt(),))
    assert len(trail.events) == len(trail.attempts) == 1


def test_execution_audit_trail_rejects_duplicate_events():
    with pytest.raises(ValueError, match="event_id"):
        ExecutionAuditTrail("session-1", "plan-1", (event(), event()))


def test_execution_audit_trail_rejects_duplicate_attempts():
    with pytest.raises(ValueError, match="attempt_id"):
        ExecutionAuditTrail("session-1", "plan-1", attempts=(attempt(), attempt()))


def test_execution_audit_trail_sorts_events_deterministically():
    trail = ExecutionAuditTrail("session-1", "plan-1", (event("z", 2), event("b", 1), event("a", 1)))
    assert [item.event_id for item in trail.events] == ["a", "b", "z"]


def test_execution_audit_trail_sorts_attempts_deterministically():
    items = (attempt(attempt_id="z", attempt_number=2), attempt(attempt_id="b"), attempt(attempt_id="a"))
    trail = ExecutionAuditTrail("session-1", "plan-1", attempts=items)
    assert [item.attempt_id for item in trail.attempts] == ["a", "b", "z"]


def test_models_are_frozen():
    for item in (context(), request(), event(), attempt(), rollback(), ExecutorResult(), ExecutionAuditTrail("session-1", "plan-1")):
        with pytest.raises(FrozenInstanceError):
            item.metadata = {}


def test_models_have_value_equality_and_deterministic_repr():
    assert context() == context() and repr(context()) == repr(context()) and "0x" not in repr(request())


def test_models_serialize_to_dict():
    for item in (context(), request(), event(), attempt(), rollback(), ExecutorResult(), ExecutionAuditTrail("session-1", "plan-1")):
        assert isinstance(asdict(item), dict)


def test_public_imports_are_available():
    import app.services.diagnostic_engine as public
    for model in (
        ExecutorStatus, ExecutorBlockReason, AuditEventType, ExecutionContext, ExecutorRequest,
        AuditEvent, ExecutionAttempt, RollbackPlan, ExecutorResult, ExecutionAuditTrail,
    ):
        assert getattr(public, model.__name__) is model


def test_module_contains_only_structural_declarations():
    import ast
    root = Path(__file__).resolve().parents[3]
    tree = ast.parse((root / "app/services/diagnostic_engine/executor_models.py").read_text(encoding="utf-8"))
    assert all(isinstance(node, (ast.Expr, ast.Import, ast.ImportFrom, ast.ClassDef, ast.FunctionDef)) for node in tree.body)


def test_sprint_files_are_utf8_without_bom():
    root = Path(__file__).resolve().parents[3]
    for path in (
        root / "app/services/diagnostic_engine/executor_models.py",
        root / "app/services/diagnostic_engine/__init__.py",
        Path(__file__),
    ):
        content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
