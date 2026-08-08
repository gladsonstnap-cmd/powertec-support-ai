import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import DiagnosticApprovalEngine
from app.services.diagnostic_engine.approval_models import (
    ApprovalActor, ApprovalScope, ApprovalStatus, ApprovalType,
)
from app.services.diagnostic_engine.approval_policy import DiagnosticApprovalPolicy
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction, ExecutionPlan, ExecutionRisk, ExecutionStatus, ExecutionTarget,
)


def actor(actor_type=ApprovalType.HUMAN_TECHNICIAN):
    return ApprovalActor(f"actor-{actor_type.value.lower()}", actor_type)


def action(**overrides):
    values = {
        "action_id": "action-1", "action_name": "restart_service", "title": "Reiniciar serviço",
        "description": "Ação descritiva; nada foi executado.", "target": ExecutionTarget.WINDOWS,
        "status": ExecutionStatus.READY, "risk": ExecutionRisk.MEDIUM, "parameters": (),
        "timeout_seconds": 30, "requires_confirmation": True, "requires_human": False,
        "metadata": {"action_kind": "state_changing", "source": "test"},
    }
    values.update(overrides)
    return ExecutionAction(**values)


def plan(item=None):
    selected = action() if item is None else item
    return ExecutionPlan("plan-1", ExecutionStatus.READY, (selected,), selected.action_id)


def engine_result(item=None, policy=None, **kwargs):
    selected = action() if item is None else item
    return DiagnosticApprovalEngine(policy).create_request(plan(selected), selected, now_monotonic=10.0, **kwargs)


def approved_bundle(item=None, policy=None):
    selected = action() if item is None else item
    engine = DiagnosticApprovalEngine(policy)
    request = engine.create_request(plan(selected), selected, now_monotonic=10.0).request
    decision = engine.decide(request, ApprovalStatus.APPROVED, actor(request.required_actor_type), 11.0).decision
    grant = engine.create_grant(request, decision, selected, 11.0).grant
    return engine, selected, request, decision, grant


def test_default_constructor():
    assert isinstance(DiagnosticApprovalEngine().policy, DiagnosticApprovalPolicy)


def test_custom_policy_is_preserved():
    policy = DiagnosticApprovalPolicy(require_approval_for_low_risk=True)
    assert DiagnosticApprovalEngine(policy).policy is policy


@pytest.mark.parametrize("risk", list(ExecutionRisk))
def test_create_request_for_each_risk(risk):
    policy = DiagnosticApprovalPolicy(require_approval_for_low_risk=True)
    result = engine_result(action(risk=risk), policy)
    assert result.success and result.request.risk == risk


def test_default_low_risk_does_not_require_request():
    result = engine_result(action(risk=ExecutionRisk.LOW))
    assert not result.success and "does not require" in result.errors[0]


def test_action_must_belong_to_plan():
    result = DiagnosticApprovalEngine().create_request(plan(), action(action_id="other"))
    assert not result.success and "belong" in result.errors[0]


@pytest.mark.parametrize(
    ("field", "invalid"),
    [("status", "READY"), ("target", "WINDOWS"), ("risk", "MEDIUM")],
)
def test_create_request_rejects_invalid_action_enums(field, invalid):
    item = action(**{field: invalid})
    result = DiagnosticApprovalEngine().create_request(plan(item), item)
    assert not result.success and field in result.errors[0]


def test_create_request_rejects_invalid_plan_status():
    item = action()
    source = ExecutionPlan("plan-1", "READY", (item,), item.action_id)
    result = DiagnosticApprovalEngine().create_request(source, item)
    assert not result.success and "execution_plan.status" in result.errors[0]


@pytest.mark.parametrize(
    ("scope", "allowed"),
    [(ApprovalScope.SINGLE_ACTION, True), (ApprovalScope.EXECUTION_PLAN, False), (ApprovalScope.SESSION, False)],
)
def test_scope_policy(scope, allowed):
    assert engine_result(scope=scope).success is allowed


def test_custom_scope_is_allowed():
    policy = DiagnosticApprovalPolicy(allow_scope_execution_plan=True)
    assert engine_result(policy=policy, scope=ApprovalScope.EXECUTION_PLAN).success


@pytest.mark.parametrize("target", [ExecutionTarget.WINDOWS, ExecutionTarget.LOCAL_MACHINE, ExecutionTarget.NETWORK])
def test_known_target_is_allowed(target):
    assert engine_result(action(target=target)).success


def test_unknown_target_is_blocked():
    result = engine_result(action(target=ExecutionTarget.UNKNOWN))
    assert not result.success and "UNKNOWN" in result.errors[0]


def test_unknown_target_can_be_explicitly_allowed():
    policy = DiagnosticApprovalPolicy(allow_approval_of_unknown_target=True)
    assert engine_result(action(target=ExecutionTarget.UNKNOWN), policy).success


def test_blocked_action_is_blocked_by_default():
    assert not engine_result(action(status=ExecutionStatus.BLOCKED)).success


def test_blocked_action_can_be_requested_without_changing_status():
    item = action(status=ExecutionStatus.BLOCKED)
    result = engine_result(item, DiagnosticApprovalPolicy(allow_approval_of_blocked_action=True))
    assert result.success and result.request.action_snapshot.status == ExecutionStatus.BLOCKED


def test_destructive_action_is_blocked_by_default():
    assert not engine_result(action(metadata={"action_kind": "destructive"})).success


def test_destructive_action_can_be_explicitly_allowed():
    policy = DiagnosticApprovalPolicy(allow_approval_of_destructive_action=True)
    assert engine_result(action(metadata={"action_kind": "destructive"}), policy).success


@pytest.mark.parametrize(
    ("risk", "required"),
    [
        (ExecutionRisk.LOW, ApprovalType.USER_CONFIRMATION),
        (ExecutionRisk.MEDIUM, ApprovalType.USER_CONFIRMATION),
        (ExecutionRisk.HIGH, ApprovalType.HUMAN_TECHNICIAN),
        (ExecutionRisk.CRITICAL, ApprovalType.ADMINISTRATOR),
    ],
)
def test_required_actor_by_risk(risk, required):
    policy = DiagnosticApprovalPolicy(require_approval_for_low_risk=True)
    assert engine_result(action(risk=risk), policy).request.required_actor_type == required


@pytest.mark.parametrize(
    ("required_risk", "actual", "allowed"),
    [
        (ExecutionRisk.MEDIUM, ApprovalType.USER_CONFIRMATION, True),
        (ExecutionRisk.MEDIUM, ApprovalType.HUMAN_TECHNICIAN, True),
        (ExecutionRisk.MEDIUM, ApprovalType.ADMINISTRATOR, True),
        (ExecutionRisk.HIGH, ApprovalType.USER_CONFIRMATION, False),
        (ExecutionRisk.HIGH, ApprovalType.HUMAN_TECHNICIAN, True),
        (ExecutionRisk.HIGH, ApprovalType.ADMINISTRATOR, True),
        (ExecutionRisk.CRITICAL, ApprovalType.HUMAN_TECHNICIAN, False),
        (ExecutionRisk.CRITICAL, ApprovalType.ADMINISTRATOR, True),
    ],
)
def test_actor_hierarchy(required_risk, actual, allowed):
    item = action(risk=required_risk)
    request = engine_result(item).request
    result = DiagnosticApprovalEngine().decide(request, ApprovalStatus.APPROVED, actor(actual), 11.0)
    assert result.success is allowed


def test_policy_override_is_blocked_by_default():
    request = engine_result().request
    assert not DiagnosticApprovalEngine().decide(request, ApprovalStatus.APPROVED, actor(ApprovalType.POLICY_OVERRIDE), 11).success


def test_policy_override_can_satisfy_non_admin_when_enabled():
    policy = DiagnosticApprovalPolicy(allow_policy_override=True)
    request = engine_result(policy=policy).request
    assert DiagnosticApprovalEngine(policy).decide(request, ApprovalStatus.APPROVED, actor(ApprovalType.POLICY_OVERRIDE), 11).success


def test_required_actor_must_be_enabled():
    policy = DiagnosticApprovalPolicy(allow_human_technician=False)
    result = engine_result(action(risk=ExecutionRisk.HIGH), policy)
    assert not result.success and "blocked" in result.errors[0]


def test_default_ttl():
    request = engine_result().request
    assert request.expires_at_monotonic == 310.0


@pytest.mark.parametrize("ttl", [1, 30, 3600])
def test_custom_valid_ttl(ttl):
    assert engine_result(ttl_seconds=ttl).request.expires_at_monotonic == 10.0 + ttl


@pytest.mark.parametrize("ttl", [0, -1, 3601, True, 1.5, "30"])
def test_invalid_ttl_is_rejected(ttl):
    result = engine_result(ttl_seconds=ttl)
    assert not result.success and "ttl_seconds" in result.errors[0]


def test_request_id_is_deterministic():
    assert engine_result().request.approval_id == "approval-plan-1-action-1"


def test_same_input_creates_same_request():
    assert engine_result() == engine_result()


@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.CANCELLED, ApprovalStatus.EXPIRED])
def test_decide_accepts_terminal_statuses(status):
    request = engine_result().request
    result = DiagnosticApprovalEngine().decide(request, status, actor(ApprovalType.USER_CONFIRMATION), 11)
    assert result.success and result.decision.status == status


@pytest.mark.parametrize("status", [ApprovalStatus.PENDING, ApprovalStatus.USED])
def test_decide_rejects_non_decision_statuses(status):
    request = engine_result().request
    assert not DiagnosticApprovalEngine().decide(request, status, actor(), 11).success


def test_decide_rejects_expired_request():
    request = engine_result(ttl_seconds=1).request
    result = DiagnosticApprovalEngine().decide(request, ApprovalStatus.APPROVED, actor(), 11)
    assert not result.success and "expirou" in result.errors[0]


def test_decide_rejects_non_pending_request():
    request = replace(engine_result().request, status=ApprovalStatus.REJECTED)
    assert not DiagnosticApprovalEngine().decide(request, ApprovalStatus.REJECTED, actor(), 11).success


def test_decide_rejects_invalid_actor_value():
    request = engine_result().request
    assert not DiagnosticApprovalEngine().decide(request, ApprovalStatus.APPROVED, "actor", 11).success


def test_decision_reason_is_preserved():
    request = engine_result().request
    result = DiagnosticApprovalEngine().decide(request, ApprovalStatus.APPROVED, actor(), 11, "Autorizado")
    assert result.decision.reason == "Autorizado"


def test_create_grant_from_approved_decision():
    _, _, request, decision, grant = approved_bundle()
    assert grant.approval_id == request.approval_id == decision.approval_id


@pytest.mark.parametrize("status", [ApprovalStatus.REJECTED, ApprovalStatus.CANCELLED, ApprovalStatus.EXPIRED])
def test_create_grant_rejects_non_approved_decision(status):
    item = action()
    engine = DiagnosticApprovalEngine()
    request = engine_result().request
    decision = engine.decide(request, status, actor(), 11).decision
    assert not engine.create_grant(request, decision, item, 11).success


def test_create_grant_rejects_inconsistent_approval_id():
    engine, item, request, decision, _ = approved_bundle()
    decision = replace(decision, approval_id="other")
    assert not engine.create_grant(request, decision, item, 11).success


def test_create_grant_rejects_inconsistent_action_id():
    engine, _, request, decision, _ = approved_bundle()
    assert not engine.create_grant(request, decision, action(action_id="other"), 11).success


def test_create_grant_rejects_inconsistent_snapshot():
    engine, item, request, decision, _ = approved_bundle()
    changed = replace(item, title="Mudou")
    assert not engine.create_grant(request, decision, changed, 11).success


def test_grant_id_is_deterministic():
    assert approved_bundle()[4].grant_id == "grant-approval-plan-1-action-1-action-1"


def test_grant_copies_approved_snapshot():
    _, _, request, _, grant = approved_bundle()
    assert grant.action_snapshot == request.action_snapshot
    assert grant.action_snapshot is not request.action_snapshot


def test_grant_expires_with_request():
    _, _, request, _, grant = approved_bundle()
    assert grant.expires_at_monotonic == request.expires_at_monotonic


def test_validate_grant_valid():
    engine, item, _, _, grant = approved_bundle()
    assert engine.validate_grant(grant, item, 12).success


@pytest.mark.parametrize("now", [310, 311])
def test_validate_grant_expired(now):
    engine, item, _, _, grant = approved_bundle()
    assert not engine.validate_grant(grant, item, now).success


def test_validate_grant_used():
    engine, item, _, _, grant = approved_bundle()
    assert not engine.validate_grant(replace(grant, used=True), item, 12).success


def test_validate_grant_wrong_action():
    engine, _, _, _, grant = approved_bundle()
    assert not engine.validate_grant(grant, action(action_id="other"), 12).success


def test_validate_grant_wrong_snapshot():
    engine, item, _, _, grant = approved_bundle()
    assert not engine.validate_grant(grant, replace(item, title="Other"), 12).success


def test_consume_grant_marks_new_grant_used():
    engine, item, _, _, grant = approved_bundle()
    result = engine.consume_grant(grant, item, 12)
    assert result.success and result.grant.used is True


def test_consume_grant_preserves_original():
    engine, item, _, _, grant = approved_bundle()
    engine.consume_grant(grant, item, 12)
    assert grant.used is False


@pytest.mark.parametrize("condition", ["used", "expired", "wrong_action"])
def test_consume_grant_rejects_invalid_grant(condition):
    engine, item, _, _, grant = approved_bundle()
    if condition == "used": grant = replace(grant, used=True)
    if condition == "expired": return_value = engine.consume_grant(grant, item, 310)
    elif condition == "wrong_action": return_value = engine.consume_grant(grant, action(action_id="other"), 12)
    else: return_value = engine.consume_grant(grant, item, 12)
    assert not return_value.success


def test_single_use_false_allows_repeated_consumption_when_used_grants_allowed():
    policy = DiagnosticApprovalPolicy(single_use_grants=False, reject_used_grants=False)
    engine, item, _, _, grant = approved_bundle(policy=policy)
    used = engine.consume_grant(grant, item, 12).grant
    assert engine.consume_grant(used, item, 13).success


@pytest.mark.parametrize(
    ("status", "allowed"),
    [(ApprovalStatus.REJECTED, False), (ApprovalStatus.EXPIRED, True), (ApprovalStatus.CANCELLED, False)],
)
def test_replacement_request_defaults(status, allowed):
    request = engine_result().request
    decision = DiagnosticApprovalEngine().decide(request, status, actor(), 11).decision
    assert DiagnosticApprovalEngine().can_create_replacement_request(request, decision) is allowed


@pytest.mark.parametrize(
    ("status", "flag"),
    [
        (ApprovalStatus.REJECTED, "allow_reuse_after_rejection"),
        (ApprovalStatus.EXPIRED, "allow_reuse_after_expiration"),
        (ApprovalStatus.CANCELLED, "allow_reuse_after_cancellation"),
    ],
)
def test_replacement_request_custom_policy(status, flag):
    policy = DiagnosticApprovalPolicy(**{flag: True})
    request = engine_result(policy=policy).request
    decision = DiagnosticApprovalEngine(policy).decide(request, status, actor(), 11).decision
    assert DiagnosticApprovalEngine(policy).can_create_replacement_request(request, decision)


def test_metadata_is_preserved():
    assert engine_result().request.metadata["source"] == "test"


def test_metadata_can_be_removed():
    result = engine_result(policy=DiagnosticApprovalPolicy(preserve_metadata=False))
    assert result.request.metadata == {}


@pytest.mark.parametrize("secret_key", ["password", "senha", "token", "secret", "segredo", "credential", "credencial", "api_key", "authorization"])
def test_secret_metadata_is_not_copied(secret_key):
    item = action(metadata={"source": "safe", secret_key: "hidden"})
    result = engine_result(item)
    assert result.success and secret_key not in result.request.metadata and secret_key not in result.request.action_snapshot.metadata


def test_reasoning_can_be_disabled():
    assert engine_result(policy=DiagnosticApprovalPolicy(preserve_reasoning=False)).reasoning == ()


def test_reasoning_is_limited():
    result = engine_result(policy=DiagnosticApprovalPolicy(max_reasoning_messages=1))
    assert len(result.reasoning) == 1


def test_errors_are_limited():
    result = DiagnosticApprovalEngine(DiagnosticApprovalPolicy(max_errors=1)).create_request(None, None)
    assert len(result.errors) == 1


def test_inputs_are_not_mutated():
    item = action(); source_plan = plan(item); before_action = deepcopy(item); before_plan = deepcopy(source_plan)
    DiagnosticApprovalEngine().create_request(source_plan, item)
    assert item == before_action and source_plan == before_plan


def test_request_and_decision_are_not_mutated():
    engine, item, request, decision, _ = approved_bundle()
    before = (deepcopy(request), deepcopy(decision))
    engine.create_grant(request, decision, item, 12)
    assert (request, decision) == before


def test_approved_does_not_mean_executed():
    engine, item, request, _, _ = approved_bundle()
    engine.decide(request, ApprovalStatus.APPROVED, actor(), 12)
    assert item.status == ExecutionStatus.READY


def test_used_does_not_mean_success():
    engine, item, _, _, grant = approved_bundle()
    consumed = engine.consume_grant(grant, item, 12).grant
    assert consumed.used and consumed.action_snapshot.status != ExecutionStatus.SUCCESS


def test_public_import():
    from app.services.diagnostic_engine import DiagnosticApprovalEngine as PublicEngine
    assert PublicEngine is DiagnosticApprovalEngine


def test_engine_module_has_no_external_or_execution_imports():
    root = Path(__file__).resolve().parents[3]
    tree = ast.parse((root / "app/services/diagnostic_engine/approval_engine.py").read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not imports & {"subprocess", "os", "socket", "requests", "asyncio", "threading"}


def test_sprint_files_are_utf8_without_bom():
    root = Path(__file__).resolve().parents[3]
    for path in (root / "app/services/diagnostic_engine/approval_engine.py", root / "app/services/diagnostic_engine/__init__.py", Path(__file__)):
        content = path.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
