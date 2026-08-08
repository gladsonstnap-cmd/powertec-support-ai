import ast
from dataclasses import FrozenInstanceError, asdict, fields
from pathlib import Path

import pytest

from app.services.diagnostic_engine import DiagnosticApprovalPolicy
from app.services.diagnostic_engine.approval_models import ApprovalScope, ApprovalStatus, ApprovalType
from app.services.diagnostic_engine.execution_models import ExecutionRisk


INTEGER_FIELDS = (
    "max_pending_requests",
    "max_requests_per_session",
    "max_reasoning_messages",
    "max_errors",
    "default_approval_ttl_seconds",
    "max_approval_ttl_seconds",
)

BOOLEAN_FIELDS = tuple(
    field.name for field in fields(DiagnosticApprovalPolicy) if field.name not in INTEGER_FIELDS
)


def test_default_policy_has_expected_integer_limits() -> None:
    policy = DiagnosticApprovalPolicy()

    assert {name: getattr(policy, name) for name in INTEGER_FIELDS} == {
        "max_pending_requests": 20,
        "max_requests_per_session": 50,
        "max_reasoning_messages": 20,
        "max_errors": 20,
        "default_approval_ttl_seconds": 300,
        "max_approval_ttl_seconds": 3600,
    }


def test_default_policy_has_expected_boolean_rules() -> None:
    policy = DiagnosticApprovalPolicy()

    assert {name: getattr(policy, name) for name in BOOLEAN_FIELDS} == {
        "single_use_grants": True,
        "allow_reuse_after_rejection": False,
        "allow_reuse_after_expiration": True,
        "allow_reuse_after_cancellation": False,
        "allow_scope_single_action": True,
        "allow_scope_execution_plan": False,
        "allow_scope_session": False,
        "allow_user_confirmation": True,
        "allow_human_technician": True,
        "allow_administrator": True,
        "allow_policy_override": False,
        "require_approval_for_low_risk": False,
        "require_approval_for_medium_risk": True,
        "require_approval_for_high_risk": True,
        "require_approval_for_critical_risk": True,
        "require_human_for_low_risk": False,
        "require_human_for_medium_risk": False,
        "require_human_for_high_risk": True,
        "require_human_for_critical_risk": True,
        "require_admin_for_low_risk": False,
        "require_admin_for_medium_risk": False,
        "require_admin_for_high_risk": False,
        "require_admin_for_critical_risk": True,
        "allow_approval_of_blocked_action": False,
        "allow_approval_of_destructive_action": False,
        "allow_approval_of_unknown_target": False,
        "preserve_reasoning": True,
        "preserve_metadata": True,
        "reject_expired_requests": True,
        "reject_used_grants": True,
    }


def test_policy_has_only_the_contract_fields() -> None:
    assert tuple(field.name for field in fields(DiagnosticApprovalPolicy)) == INTEGER_FIELDS + BOOLEAN_FIELDS


def test_policy_is_frozen() -> None:
    policy = DiagnosticApprovalPolicy()
    with pytest.raises(FrozenInstanceError):
        policy.max_pending_requests = 99  # type: ignore[misc]


def test_policy_supports_value_equality() -> None:
    assert DiagnosticApprovalPolicy() == DiagnosticApprovalPolicy()


def test_policy_repr_identifies_type() -> None:
    assert repr(DiagnosticApprovalPolicy()).startswith("DiagnosticApprovalPolicy(")


def test_policy_can_be_serialized_to_plain_values() -> None:
    values = asdict(DiagnosticApprovalPolicy())
    assert len(values) == 36
    assert values["single_use_grants"] is True


def test_custom_values_are_preserved() -> None:
    policy = DiagnosticApprovalPolicy(
        max_pending_requests=1,
        default_approval_ttl_seconds=10,
        max_approval_ttl_seconds=20,
        allow_scope_session=True,
        require_approval_for_low_risk=True,
    )
    assert policy.max_pending_requests == 1
    assert policy.default_approval_ttl_seconds == 10
    assert policy.max_approval_ttl_seconds == 20
    assert policy.allow_scope_session is True
    assert policy.require_approval_for_low_risk is True


@pytest.mark.parametrize("field_name", INTEGER_FIELDS)
def test_each_integer_field_rejects_zero(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        DiagnosticApprovalPolicy(**{field_name: 0})


@pytest.mark.parametrize("field_name", INTEGER_FIELDS)
def test_each_integer_field_rejects_negative_values(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        DiagnosticApprovalPolicy(**{field_name: -1})


@pytest.mark.parametrize("field_name", INTEGER_FIELDS)
def test_each_integer_field_rejects_bool(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        DiagnosticApprovalPolicy(**{field_name: True})


@pytest.mark.parametrize("invalid", [1.5, "10", None])
def test_integer_field_rejects_other_types(invalid: object) -> None:
    with pytest.raises(ValueError, match="max_pending_requests"):
        DiagnosticApprovalPolicy(max_pending_requests=invalid)  # type: ignore[arg-type]


def test_each_integer_field_accepts_positive_integer() -> None:
    for field_name in INTEGER_FIELDS:
        kwargs = {field_name: 1}
        if field_name == "max_approval_ttl_seconds":
            kwargs["default_approval_ttl_seconds"] = 1
        assert getattr(DiagnosticApprovalPolicy(**kwargs), field_name) == 1


def test_default_ttl_cannot_exceed_maximum() -> None:
    with pytest.raises(ValueError, match="default_approval_ttl_seconds"):
        DiagnosticApprovalPolicy(default_approval_ttl_seconds=11, max_approval_ttl_seconds=10)


def test_default_ttl_may_equal_maximum() -> None:
    policy = DiagnosticApprovalPolicy(default_approval_ttl_seconds=10, max_approval_ttl_seconds=10)
    assert policy.default_approval_ttl_seconds == policy.max_approval_ttl_seconds


def test_each_boolean_field_rejects_non_boolean() -> None:
    for field_name in BOOLEAN_FIELDS:
        with pytest.raises(ValueError, match=field_name):
            DiagnosticApprovalPolicy(**{field_name: 1})


@pytest.mark.parametrize(
    ("scope", "expected"),
    [(ApprovalScope.SINGLE_ACTION, True), (ApprovalScope.EXECUTION_PLAN, False), (ApprovalScope.SESSION, False)],
)
def test_is_scope_allowed_uses_scope_rule(scope: ApprovalScope, expected: bool) -> None:
    assert DiagnosticApprovalPolicy().is_scope_allowed(scope) is expected


@pytest.mark.parametrize("scope", list(ApprovalScope))
def test_is_scope_allowed_honors_custom_configuration(scope: ApprovalScope) -> None:
    policy = DiagnosticApprovalPolicy(
        allow_scope_single_action=False, allow_scope_execution_plan=True, allow_scope_session=True
    )
    assert policy.is_scope_allowed(scope) is (scope is not ApprovalScope.SINGLE_ACTION)


@pytest.mark.parametrize(
    ("actor_type", "expected"),
    [
        (ApprovalType.USER_CONFIRMATION, True),
        (ApprovalType.HUMAN_TECHNICIAN, True),
        (ApprovalType.ADMINISTRATOR, True),
        (ApprovalType.POLICY_OVERRIDE, False),
    ],
)
def test_is_actor_type_allowed_uses_actor_rule(actor_type: ApprovalType, expected: bool) -> None:
    assert DiagnosticApprovalPolicy().is_actor_type_allowed(actor_type) is expected


@pytest.mark.parametrize(
    ("risk", "expected"),
    [(ExecutionRisk.LOW, False), (ExecutionRisk.MEDIUM, True), (ExecutionRisk.HIGH, True), (ExecutionRisk.CRITICAL, True)],
)
def test_requires_approval_uses_risk_rule(risk: ExecutionRisk, expected: bool) -> None:
    assert DiagnosticApprovalPolicy().requires_approval(risk) is expected


@pytest.mark.parametrize(
    ("risk", "expected"),
    [(ExecutionRisk.LOW, False), (ExecutionRisk.MEDIUM, False), (ExecutionRisk.HIGH, True), (ExecutionRisk.CRITICAL, True)],
)
def test_requires_human_uses_risk_rule(risk: ExecutionRisk, expected: bool) -> None:
    assert DiagnosticApprovalPolicy().requires_human(risk) is expected


@pytest.mark.parametrize(
    ("risk", "expected"),
    [(ExecutionRisk.LOW, False), (ExecutionRisk.MEDIUM, False), (ExecutionRisk.HIGH, False), (ExecutionRisk.CRITICAL, True)],
)
def test_requires_admin_uses_risk_rule(risk: ExecutionRisk, expected: bool) -> None:
    assert DiagnosticApprovalPolicy().requires_admin(risk) is expected


@pytest.mark.parametrize("ttl", [1, 300, 3599, 3600])
def test_validate_ttl_accepts_positive_values_within_limit(ttl: int) -> None:
    assert DiagnosticApprovalPolicy().validate_ttl(ttl) is True


@pytest.mark.parametrize("ttl", [0, -1, 3601, True, 1.5, "300", None])
def test_validate_ttl_rejects_invalid_values(ttl: object) -> None:
    assert DiagnosticApprovalPolicy().validate_ttl(ttl) is False  # type: ignore[arg-type]


def test_validate_ttl_uses_custom_maximum() -> None:
    policy = DiagnosticApprovalPolicy(default_approval_ttl_seconds=10, max_approval_ttl_seconds=20)
    assert policy.validate_ttl(20) is True
    assert policy.validate_ttl(21) is False


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ApprovalStatus.PENDING, False),
        (ApprovalStatus.APPROVED, False),
        (ApprovalStatus.REJECTED, False),
        (ApprovalStatus.EXPIRED, True),
        (ApprovalStatus.CANCELLED, False),
        (ApprovalStatus.USED, False),
    ],
)
def test_can_reuse_after_uses_status_rule(status: ApprovalStatus, expected: bool) -> None:
    assert DiagnosticApprovalPolicy().can_reuse_after(status) is expected


def test_can_reuse_after_honors_custom_reuse_configuration() -> None:
    policy = DiagnosticApprovalPolicy(
        allow_reuse_after_rejection=True,
        allow_reuse_after_expiration=False,
        allow_reuse_after_cancellation=True,
    )
    assert policy.can_reuse_after(ApprovalStatus.REJECTED) is True
    assert policy.can_reuse_after(ApprovalStatus.EXPIRED) is False
    assert policy.can_reuse_after(ApprovalStatus.CANCELLED) is True


def test_policy_module_contains_only_declarations() -> None:
    backend_root = Path(__file__).resolve().parents[3]
    source = (backend_root / "app/services/diagnostic_engine/approval_policy.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    assert all(isinstance(node, (ast.Expr, ast.Import, ast.ImportFrom, ast.ClassDef)) for node in module.body)


def test_sprint_files_are_utf8_without_bom() -> None:
    backend_root = Path(__file__).resolve().parents[3]
    paths = (
        backend_root / "app/services/diagnostic_engine/approval_policy.py",
        backend_root / "app/services/diagnostic_engine/__init__.py",
        backend_root / "tests/services/diagnostic_engine/test_approval_policy.py",
    )
    for path in paths:
        content = path.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
