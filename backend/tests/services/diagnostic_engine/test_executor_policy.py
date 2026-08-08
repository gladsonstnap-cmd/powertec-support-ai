import ast
from dataclasses import FrozenInstanceError, asdict, fields
from pathlib import Path

import pytest

from app.services.diagnostic_engine import DiagnosticExecutorPolicy
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.executor_models import ExecutorStatus


INTEGER_FIELDS = (
    "max_attempts_per_action",
    "max_total_attempts_per_session",
    "max_audit_events_per_request",
    "max_reasoning_messages",
    "max_errors",
    "default_timeout_seconds",
    "max_timeout_seconds",
)

BOOLEAN_FIELDS = tuple(
    item.name for item in fields(DiagnosticExecutorPolicy) if item.name not in INTEGER_FIELDS
)


def test_default_policy_has_expected_integer_limits():
    policy = DiagnosticExecutorPolicy()
    assert {name: getattr(policy, name) for name in INTEGER_FIELDS} == {
        "max_attempts_per_action": 1,
        "max_total_attempts_per_session": 20,
        "max_audit_events_per_request": 100,
        "max_reasoning_messages": 20,
        "max_errors": 20,
        "default_timeout_seconds": 30,
        "max_timeout_seconds": 300,
    }


def test_default_policy_has_expected_flags():
    assert {name: getattr(DiagnosticExecutorPolicy(), name) for name in BOOLEAN_FIELDS} == {
        "require_valid_grant": True,
        "require_unexpired_grant": True,
        "reject_used_grants": True,
        "require_action_snapshot_match": True,
        "require_plan_match": True,
        "require_session_match": True,
        "allow_local_execution": False,
        "allow_remote_execution": False,
        "allow_windows_target": True,
        "allow_linux_target": False,
        "allow_network_target": True,
        "allow_unknown_target": False,
        "allow_remote_agent_target": False,
        "allow_low_risk": True,
        "allow_medium_risk": False,
        "allow_high_risk": False,
        "allow_critical_risk": False,
        "require_dry_run_for_low_risk": False,
        "require_dry_run_for_medium_risk": True,
        "require_dry_run_for_high_risk": True,
        "require_dry_run_for_critical_risk": True,
        "allow_read_only_actions": True,
        "allow_state_changing_actions": False,
        "allow_destructive_actions": False,
        "require_audit_trail": True,
        "require_validation_event": True,
        "require_authorization_event": True,
        "require_start_event": True,
        "require_terminal_event": True,
        "allow_retry_after_failure": False,
        "allow_retry_after_timeout": False,
        "allow_retry_after_blocked": False,
        "allow_rollback": False,
        "require_rollback_plan_for_state_change": True,
        "require_confirmation_before_rollback": True,
        "require_human_before_rollback": True,
        "stop_after_failure": True,
        "stop_after_timeout": True,
        "stop_after_blocked": True,
        "preserve_reasoning": True,
        "preserve_metadata": True,
    }


def test_policy_has_only_contract_fields():
    assert tuple(item.name for item in fields(DiagnosticExecutorPolicy)) == INTEGER_FIELDS + BOOLEAN_FIELDS


def test_custom_policy_preserves_values():
    policy = DiagnosticExecutorPolicy(
        max_attempts_per_action=3, default_timeout_seconds=10, max_timeout_seconds=60,
        allow_local_execution=True, allow_medium_risk=True, allow_rollback=True,
    )
    assert policy.max_attempts_per_action == 3 and policy.max_timeout_seconds == 60
    assert policy.allow_local_execution and policy.allow_medium_risk and policy.allow_rollback


def test_policy_is_frozen():
    with pytest.raises(FrozenInstanceError):
        DiagnosticExecutorPolicy().allow_local_execution = True


def test_policy_has_value_equality():
    assert DiagnosticExecutorPolicy() == DiagnosticExecutorPolicy()
    assert DiagnosticExecutorPolicy(max_errors=1) != DiagnosticExecutorPolicy()


def test_policy_repr_is_deterministic():
    assert repr(DiagnosticExecutorPolicy()) == repr(DiagnosticExecutorPolicy())
    assert "0x" not in repr(DiagnosticExecutorPolicy())


def test_policy_serializes_to_plain_values():
    assert len(asdict(DiagnosticExecutorPolicy())) == 48


@pytest.mark.parametrize("field_name", INTEGER_FIELDS)
def test_each_integer_field_rejects_zero(field_name):
    with pytest.raises(ValueError, match=field_name):
        DiagnosticExecutorPolicy(**{field_name: 0})


@pytest.mark.parametrize("field_name", INTEGER_FIELDS)
def test_each_integer_field_rejects_negative(field_name):
    with pytest.raises(ValueError, match=field_name):
        DiagnosticExecutorPolicy(**{field_name: -1})


@pytest.mark.parametrize("field_name", INTEGER_FIELDS)
def test_each_integer_field_rejects_bool(field_name):
    with pytest.raises(ValueError, match=field_name):
        DiagnosticExecutorPolicy(**{field_name: True})


@pytest.mark.parametrize("invalid", [1.5, "20", None])
def test_integer_field_rejects_other_types(invalid):
    with pytest.raises(ValueError, match="max_attempts_per_action"):
        DiagnosticExecutorPolicy(max_attempts_per_action=invalid)


def test_each_integer_field_accepts_positive_integer():
    for field_name in INTEGER_FIELDS:
        overrides = {field_name: 1}
        if field_name == "max_timeout_seconds":
            overrides["default_timeout_seconds"] = 1
        assert getattr(DiagnosticExecutorPolicy(**overrides), field_name) == 1


def test_default_timeout_cannot_exceed_maximum():
    with pytest.raises(ValueError, match="default_timeout_seconds"):
        DiagnosticExecutorPolicy(default_timeout_seconds=31, max_timeout_seconds=30)


def test_default_timeout_can_equal_maximum():
    policy = DiagnosticExecutorPolicy(default_timeout_seconds=30, max_timeout_seconds=30)
    assert policy.default_timeout_seconds == policy.max_timeout_seconds


def test_each_boolean_field_rejects_non_boolean():
    for field_name in BOOLEAN_FIELDS:
        with pytest.raises(ValueError, match=field_name):
            DiagnosticExecutorPolicy(**{field_name: 1})


def test_all_flags_can_be_customized():
    default = DiagnosticExecutorPolicy()
    custom = DiagnosticExecutorPolicy(**{name: not getattr(default, name) for name in BOOLEAN_FIELDS})
    assert all(getattr(custom, name) is not getattr(default, name) for name in BOOLEAN_FIELDS)


@pytest.mark.parametrize(
    ("target", "allowed"),
    [
        (ExecutionTarget.LOCAL_MACHINE, False),
        (ExecutionTarget.WINDOWS, True),
        (ExecutionTarget.LINUX, False),
        (ExecutionTarget.NETWORK, True),
        (ExecutionTarget.REMOTE_AGENT, False),
        (ExecutionTarget.UNKNOWN, False),
    ],
)
def test_target_defaults(target, allowed):
    assert DiagnosticExecutorPolicy().is_target_allowed(target) is allowed


@pytest.mark.parametrize("target", list(ExecutionTarget))
def test_target_allowance_honors_custom_flags(target):
    policy = DiagnosticExecutorPolicy(
        allow_local_execution=True, allow_windows_target=False, allow_linux_target=True,
        allow_network_target=False, allow_remote_agent_target=True, allow_unknown_target=True,
    )
    expected = target in {
        ExecutionTarget.LOCAL_MACHINE, ExecutionTarget.LINUX,
        ExecutionTarget.REMOTE_AGENT, ExecutionTarget.UNKNOWN,
    }
    assert policy.is_target_allowed(target) is expected


@pytest.mark.parametrize(
    ("risk", "allowed"),
    [
        (ExecutionRisk.LOW, True), (ExecutionRisk.MEDIUM, False),
        (ExecutionRisk.HIGH, False), (ExecutionRisk.CRITICAL, False),
    ],
)
def test_risk_defaults(risk, allowed):
    assert DiagnosticExecutorPolicy().is_risk_allowed(risk) is allowed


@pytest.mark.parametrize("risk", list(ExecutionRisk))
def test_risk_allowance_honors_custom_flags(risk):
    policy = DiagnosticExecutorPolicy(
        allow_low_risk=False, allow_medium_risk=True, allow_high_risk=True, allow_critical_risk=True,
    )
    assert policy.is_risk_allowed(risk) is (risk is not ExecutionRisk.LOW)


@pytest.mark.parametrize(
    ("risk", "required"),
    [
        (ExecutionRisk.LOW, False), (ExecutionRisk.MEDIUM, True),
        (ExecutionRisk.HIGH, True), (ExecutionRisk.CRITICAL, True),
    ],
)
def test_dry_run_defaults(risk, required):
    assert DiagnosticExecutorPolicy().requires_dry_run(risk) is required


def test_dry_run_honors_custom_flags():
    policy = DiagnosticExecutorPolicy(
        require_dry_run_for_low_risk=True, require_dry_run_for_medium_risk=False,
        require_dry_run_for_high_risk=False, require_dry_run_for_critical_risk=False,
    )
    assert policy.requires_dry_run(ExecutionRisk.LOW)
    assert not policy.requires_dry_run(ExecutionRisk.CRITICAL)


@pytest.mark.parametrize(
    ("action_type", "allowed"),
    [("read_only", True), ("state_changing", False), ("destructive", False), ("unknown", False), ("", False)],
)
def test_action_type_defaults(action_type, allowed):
    assert DiagnosticExecutorPolicy().is_action_type_allowed(action_type) is allowed


def test_action_type_honors_custom_flags():
    policy = DiagnosticExecutorPolicy(
        allow_read_only_actions=False, allow_state_changing_actions=True, allow_destructive_actions=True,
    )
    assert not policy.is_action_type_allowed("read_only")
    assert policy.is_action_type_allowed("state_changing") and policy.is_action_type_allowed("destructive")


@pytest.mark.parametrize("timeout", [1, 30, 299, 300])
def test_validate_timeout_accepts_valid_values(timeout):
    assert DiagnosticExecutorPolicy().validate_timeout(timeout)


@pytest.mark.parametrize("timeout", [0, -1, 301, True, 1.5, "30", None])
def test_validate_timeout_rejects_invalid_values(timeout):
    assert not DiagnosticExecutorPolicy().validate_timeout(timeout)


@pytest.mark.parametrize("status", list(ExecutorStatus))
def test_retry_is_disabled_by_default(status):
    assert not DiagnosticExecutorPolicy().can_retry_after(status)


@pytest.mark.parametrize(
    ("status", "flag"),
    [
        (ExecutorStatus.FAILED, "allow_retry_after_failure"),
        (ExecutorStatus.TIMED_OUT, "allow_retry_after_timeout"),
        (ExecutorStatus.BLOCKED, "allow_retry_after_blocked"),
    ],
)
def test_retry_honors_custom_flag(status, flag):
    assert DiagnosticExecutorPolicy(**{flag: True}).can_retry_after(status)


def test_rollback_is_blocked_by_default():
    assert not DiagnosticExecutorPolicy().can_use_rollback()


def test_rollback_honors_custom_flag():
    assert DiagnosticExecutorPolicy(allow_rollback=True).can_use_rollback()


def test_max_attempts_for_request_uses_configured_limit():
    assert DiagnosticExecutorPolicy(max_attempts_per_action=3).max_attempts_for_request() == 3


def test_grant_contract_defaults_are_conservative():
    policy = DiagnosticExecutorPolicy()
    assert policy.require_valid_grant and policy.require_unexpired_grant and policy.reject_used_grants
    assert policy.require_action_snapshot_match and policy.require_plan_match and policy.require_session_match


def test_execution_modes_are_disabled_by_default():
    policy = DiagnosticExecutorPolicy()
    assert not policy.allow_local_execution and not policy.allow_remote_execution


def test_audit_contract_defaults_are_required():
    policy = DiagnosticExecutorPolicy()
    assert policy.require_audit_trail and policy.require_validation_event
    assert policy.require_authorization_event and policy.require_start_event and policy.require_terminal_event


def test_rollback_contract_defaults_are_conservative():
    policy = DiagnosticExecutorPolicy()
    assert not policy.allow_rollback and policy.require_rollback_plan_for_state_change
    assert policy.require_confirmation_before_rollback and policy.require_human_before_rollback


def test_stop_contract_defaults_are_conservative():
    policy = DiagnosticExecutorPolicy()
    assert policy.stop_after_failure and policy.stop_after_timeout and policy.stop_after_blocked


def test_helpers_do_not_mutate_policy():
    policy = DiagnosticExecutorPolicy(); before = asdict(policy)
    policy.is_target_allowed(ExecutionTarget.WINDOWS); policy.is_risk_allowed(ExecutionRisk.LOW)
    policy.requires_dry_run(ExecutionRisk.HIGH); policy.is_action_type_allowed("read_only")
    policy.validate_timeout(30); policy.can_retry_after(ExecutorStatus.FAILED)
    policy.can_use_rollback(); policy.max_attempts_for_request()
    assert asdict(policy) == before


def test_public_import_is_available():
    from app.services.diagnostic_engine import DiagnosticExecutorPolicy as PublicPolicy
    assert PublicPolicy is DiagnosticExecutorPolicy


def test_policy_module_contains_only_declarations():
    root = Path(__file__).resolve().parents[3]
    tree = ast.parse((root / "app/services/diagnostic_engine/executor_policy.py").read_text(encoding="utf-8"))
    assert all(isinstance(node, (ast.Expr, ast.Import, ast.ImportFrom, ast.ClassDef)) for node in tree.body)


def test_sprint_files_are_utf8_without_bom():
    root = Path(__file__).resolve().parents[3]
    for path in (
        root / "app/services/diagnostic_engine/executor_policy.py",
        root / "app/services/diagnostic_engine/__init__.py",
        Path(__file__),
    ):
        content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
