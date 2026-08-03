from dataclasses import FrozenInstanceError, asdict, fields
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    DiagnosticExecutionPolicy,
    ExecutionRisk,
    ExecutionTarget,
)


INTEGER_FIELDS = (
    "max_actions",
    "max_parameters_per_action",
    "max_reasoning_messages",
    "max_errors",
    "default_timeout_seconds",
    "max_timeout_seconds",
    "max_low_risk_actions",
    "max_medium_risk_actions",
    "max_high_risk_actions",
    "max_critical_risk_actions",
)

BOOLEAN_FIELDS = (
    "allow_local_machine",
    "allow_remote_agent",
    "allow_windows",
    "allow_linux",
    "allow_network",
    "allow_unknown_target",
    "allow_low_risk",
    "allow_medium_risk",
    "allow_high_risk",
    "allow_critical_risk",
    "require_confirmation_for_low_risk",
    "require_confirmation_for_medium_risk",
    "require_confirmation_for_high_risk",
    "require_confirmation_for_critical_risk",
    "require_human_for_high_risk",
    "require_human_for_critical_risk",
    "allow_read_only_actions",
    "allow_state_changing_actions",
    "allow_destructive_actions",
    "preserve_reasoning",
    "preserve_metadata",
    "stop_after_failure",
    "stop_after_blocked",
)


def test_default_policy_values():
    assert asdict(DiagnosticExecutionPolicy()) == {
        "max_actions": 20,
        "max_parameters_per_action": 20,
        "max_reasoning_messages": 20,
        "max_errors": 20,
        "default_timeout_seconds": 30,
        "max_timeout_seconds": 300,
        "max_low_risk_actions": 20,
        "max_medium_risk_actions": 10,
        "max_high_risk_actions": 3,
        "max_critical_risk_actions": 1,
        "allow_local_machine": True,
        "allow_remote_agent": False,
        "allow_windows": True,
        "allow_linux": False,
        "allow_network": True,
        "allow_unknown_target": False,
        "allow_low_risk": True,
        "allow_medium_risk": True,
        "allow_high_risk": False,
        "allow_critical_risk": False,
        "require_confirmation_for_low_risk": False,
        "require_confirmation_for_medium_risk": True,
        "require_confirmation_for_high_risk": True,
        "require_confirmation_for_critical_risk": True,
        "require_human_for_high_risk": True,
        "require_human_for_critical_risk": True,
        "allow_read_only_actions": True,
        "allow_state_changing_actions": False,
        "allow_destructive_actions": False,
        "preserve_reasoning": True,
        "preserve_metadata": True,
        "stop_after_failure": True,
        "stop_after_blocked": True,
    }


def test_custom_policy_values():
    policy = DiagnosticExecutionPolicy(
        max_actions=5,
        default_timeout_seconds=10,
        max_timeout_seconds=60,
        allow_remote_agent=True,
        allow_high_risk=True,
        allow_state_changing_actions=True,
    )
    assert policy.max_actions == 5
    assert policy.default_timeout_seconds == 10
    assert policy.max_timeout_seconds == 60
    assert policy.allow_remote_agent is True
    assert policy.allow_high_risk is True
    assert policy.allow_state_changing_actions is True


def test_policy_is_immutable():
    with pytest.raises(FrozenInstanceError):
        DiagnosticExecutionPolicy().max_actions = 30


def test_policy_equality():
    assert DiagnosticExecutionPolicy() == DiagnosticExecutionPolicy()
    assert DiagnosticExecutionPolicy(max_actions=1) != DiagnosticExecutionPolicy()


def test_repr_is_deterministic():
    assert repr(DiagnosticExecutionPolicy()) == repr(DiagnosticExecutionPolicy())
    assert "0x" not in repr(DiagnosticExecutionPolicy())


def test_policy_has_expected_field_count():
    assert len(fields(DiagnosticExecutionPolicy)) == 33


def test_each_integer_field_accepts_one():
    for field_name in INTEGER_FIELDS:
        overrides = {field_name: 1}
        if field_name == "max_timeout_seconds":
            overrides["default_timeout_seconds"] = 1
        assert getattr(DiagnosticExecutionPolicy(**overrides), field_name) == 1


@pytest.mark.parametrize("field_name", INTEGER_FIELDS)
def test_each_integer_field_rejects_zero(field_name):
    with pytest.raises(ValueError, match=field_name):
        DiagnosticExecutionPolicy(**{field_name: 0})


@pytest.mark.parametrize("field_name", INTEGER_FIELDS)
def test_each_integer_field_rejects_negative(field_name):
    with pytest.raises(ValueError, match=field_name):
        DiagnosticExecutionPolicy(**{field_name: -1})


def test_each_integer_field_rejects_bool():
    for field_name in INTEGER_FIELDS:
        with pytest.raises(ValueError, match=field_name):
            DiagnosticExecutionPolicy(**{field_name: True})


@pytest.mark.parametrize("value", [1.5, "20", None])
def test_integer_fields_reject_other_types(value):
    with pytest.raises(ValueError, match="max_actions"):
        DiagnosticExecutionPolicy(max_actions=value)


def test_default_timeout_cannot_exceed_maximum():
    with pytest.raises(ValueError, match="default_timeout_seconds"):
        DiagnosticExecutionPolicy(default_timeout_seconds=31, max_timeout_seconds=30)


@pytest.mark.parametrize("timeout", [1, 300])
def test_validate_timeout_accepts_boundaries(timeout):
    assert DiagnosticExecutionPolicy().validate_timeout(timeout) is True


@pytest.mark.parametrize("timeout", [0, -1, 301, True, 1.5, "30", None])
def test_validate_timeout_rejects_invalid_values(timeout):
    assert DiagnosticExecutionPolicy().validate_timeout(timeout) is False


def test_default_target_flags_are_conservative():
    policy = DiagnosticExecutionPolicy()
    assert policy.allow_local_machine is True
    assert policy.allow_remote_agent is False
    assert policy.allow_windows is True
    assert policy.allow_linux is False
    assert policy.allow_network is True
    assert policy.allow_unknown_target is False


def test_default_risk_flags_are_conservative():
    policy = DiagnosticExecutionPolicy()
    assert policy.allow_low_risk is True
    assert policy.allow_medium_risk is True
    assert policy.allow_high_risk is False
    assert policy.allow_critical_risk is False


def test_flags_can_be_customized():
    policy = DiagnosticExecutionPolicy(**{name: not getattr(DiagnosticExecutionPolicy(), name) for name in BOOLEAN_FIELDS})
    assert all(getattr(policy, name) is not getattr(DiagnosticExecutionPolicy(), name) for name in BOOLEAN_FIELDS)


def test_boolean_flags_reject_non_boolean_values():
    for field_name in BOOLEAN_FIELDS:
        with pytest.raises(ValueError, match=field_name):
            DiagnosticExecutionPolicy(**{field_name: 1})


@pytest.mark.parametrize(
    ("target", "allowed"),
    [
        (ExecutionTarget.LOCAL_MACHINE, True),
        (ExecutionTarget.REMOTE_AGENT, False),
        (ExecutionTarget.WINDOWS, True),
        (ExecutionTarget.LINUX, False),
        (ExecutionTarget.NETWORK, True),
        (ExecutionTarget.UNKNOWN, False),
    ],
)
def test_target_allowance(target, allowed):
    assert DiagnosticExecutionPolicy().is_target_allowed(target) is allowed


def test_target_allowance_uses_custom_flags():
    policy = DiagnosticExecutionPolicy(allow_remote_agent=True, allow_network=False)
    assert policy.is_target_allowed(ExecutionTarget.REMOTE_AGENT) is True
    assert policy.is_target_allowed(ExecutionTarget.NETWORK) is False


@pytest.mark.parametrize(
    ("risk", "allowed"),
    [
        (ExecutionRisk.LOW, True),
        (ExecutionRisk.MEDIUM, True),
        (ExecutionRisk.HIGH, False),
        (ExecutionRisk.CRITICAL, False),
    ],
)
def test_risk_allowance(risk, allowed):
    assert DiagnosticExecutionPolicy().is_risk_allowed(risk) is allowed


@pytest.mark.parametrize(
    ("risk", "required"),
    [
        (ExecutionRisk.LOW, False),
        (ExecutionRisk.MEDIUM, True),
        (ExecutionRisk.HIGH, True),
        (ExecutionRisk.CRITICAL, True),
    ],
)
def test_confirmation_requirement(risk, required):
    assert DiagnosticExecutionPolicy().requires_confirmation(risk) is required


@pytest.mark.parametrize(
    ("risk", "required"),
    [
        (ExecutionRisk.LOW, False),
        (ExecutionRisk.MEDIUM, False),
        (ExecutionRisk.HIGH, True),
        (ExecutionRisk.CRITICAL, True),
    ],
)
def test_human_requirement(risk, required):
    assert DiagnosticExecutionPolicy().requires_human(risk) is required


@pytest.mark.parametrize(
    ("risk", "limit"),
    [
        (ExecutionRisk.LOW, 20),
        (ExecutionRisk.MEDIUM, 10),
        (ExecutionRisk.HIGH, 3),
        (ExecutionRisk.CRITICAL, 1),
    ],
)
def test_action_limit_by_risk(risk, limit):
    assert DiagnosticExecutionPolicy().max_actions_for_risk(risk) == limit


def test_action_kind_defaults_are_conservative():
    policy = DiagnosticExecutionPolicy()
    assert policy.allow_read_only_actions is True
    assert policy.allow_state_changing_actions is False
    assert policy.allow_destructive_actions is False


def test_methods_do_not_change_policy_state():
    policy = DiagnosticExecutionPolicy()
    before = asdict(policy)
    policy.is_target_allowed(ExecutionTarget.LOCAL_MACHINE)
    policy.is_risk_allowed(ExecutionRisk.LOW)
    policy.requires_confirmation(ExecutionRisk.MEDIUM)
    policy.requires_human(ExecutionRisk.HIGH)
    policy.max_actions_for_risk(ExecutionRisk.CRITICAL)
    policy.validate_timeout(30)
    assert asdict(policy) == before


def test_public_import_is_available():
    import app.services.diagnostic_engine as public

    assert public.DiagnosticExecutionPolicy is DiagnosticExecutionPolicy


def test_policy_serializes_with_asdict():
    assert asdict(DiagnosticExecutionPolicy())["max_actions"] == 20


def test_files_are_utf8_without_bom():
    root = Path(__file__).parents[3]
    paths = (
        root / "app/services/diagnostic_engine/execution_policy.py",
        root / "app/services/diagnostic_engine/__init__.py",
        Path(__file__),
    )
    for path in paths:
        content = path.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
