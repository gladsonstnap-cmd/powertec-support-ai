from dataclasses import FrozenInstanceError, asdict, fields
from pathlib import Path

import pytest

from app.services.diagnostic_engine import DiagnosticPlannerPolicy


LIMIT_FIELDS = (
    "max_steps",
    "max_question_steps",
    "max_test_steps",
    "max_confirmation_steps",
    "max_action_steps",
    "max_parallel_alternatives",
    "max_reasoning_messages",
    "max_errors",
)

CONFIDENCE_FIELDS = ("minimum_step_confidence", "minimum_plan_confidence")

BOOLEAN_FIELDS = (
    "require_confirmation_for_medium_risk",
    "require_confirmation_for_high_risk",
    "require_confirmation_for_critical_risk",
    "allow_parallel_alternatives",
    "allow_multiple_active_steps",
    "stop_after_escalation",
    "stop_after_completion",
    "preserve_reasoning",
    "preserve_metadata",
)


def test_default_policy_values():
    policy = DiagnosticPlannerPolicy()
    assert asdict(policy) == {
        "max_steps": 25,
        "max_question_steps": 10,
        "max_test_steps": 10,
        "max_confirmation_steps": 5,
        "max_action_steps": 5,
        "max_parallel_alternatives": 5,
        "max_reasoning_messages": 20,
        "max_errors": 20,
        "minimum_step_confidence": 0.40,
        "minimum_plan_confidence": 0.50,
        "require_confirmation_for_medium_risk": False,
        "require_confirmation_for_high_risk": True,
        "require_confirmation_for_critical_risk": True,
        "allow_parallel_alternatives": True,
        "allow_multiple_active_steps": False,
        "stop_after_escalation": True,
        "stop_after_completion": True,
        "preserve_reasoning": True,
        "preserve_metadata": True,
    }


def test_custom_policy_values():
    policy = DiagnosticPlannerPolicy(
        max_steps=1,
        minimum_step_confidence=0.2,
        require_confirmation_for_medium_risk=True,
        allow_parallel_alternatives=False,
    )
    assert policy.max_steps == 1
    assert policy.minimum_step_confidence == 0.2
    assert policy.require_confirmation_for_medium_risk is True
    assert policy.allow_parallel_alternatives is False


def test_policy_is_immutable():
    with pytest.raises(FrozenInstanceError):
        DiagnosticPlannerPolicy().max_steps = 30


def test_policy_equality():
    assert DiagnosticPlannerPolicy() == DiagnosticPlannerPolicy()
    assert DiagnosticPlannerPolicy(max_steps=1) != DiagnosticPlannerPolicy()


def test_policy_has_expected_field_count():
    assert len(fields(DiagnosticPlannerPolicy)) == 19


@pytest.mark.parametrize("field", LIMIT_FIELDS)
def test_each_limit_accepts_one(field):
    assert getattr(DiagnosticPlannerPolicy(**{field: 1}), field) == 1


@pytest.mark.parametrize("field", LIMIT_FIELDS)
def test_each_limit_rejects_zero(field):
    with pytest.raises(ValueError, match=field):
        DiagnosticPlannerPolicy(**{field: 0})


@pytest.mark.parametrize("field", LIMIT_FIELDS)
def test_each_limit_rejects_negative_value(field):
    with pytest.raises(ValueError, match=field):
        DiagnosticPlannerPolicy(**{field: -1})


def test_limits_reject_wrong_types():
    for field in LIMIT_FIELDS:
        for value in (1.5, "1", True, None):
            with pytest.raises(ValueError, match=field):
                DiagnosticPlannerPolicy(**{field: value})


@pytest.mark.parametrize("field", CONFIDENCE_FIELDS)
@pytest.mark.parametrize("value", [0.0, 1.0])
def test_confidence_accepts_boundaries(field, value):
    assert getattr(DiagnosticPlannerPolicy(**{field: value}), field) == value


@pytest.mark.parametrize("field", CONFIDENCE_FIELDS)
@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_confidence_rejects_out_of_range(field, value):
    with pytest.raises(ValueError, match=field):
        DiagnosticPlannerPolicy(**{field: value})


def test_confidences_reject_wrong_types():
    for field in CONFIDENCE_FIELDS:
        for value in ("0.5", True, None):
            with pytest.raises(ValueError, match=field):
                DiagnosticPlannerPolicy(**{field: value})


def test_boolean_flags_accept_boolean_values():
    for field in BOOLEAN_FIELDS:
        for value in (True, False):
            assert getattr(DiagnosticPlannerPolicy(**{field: value}), field) is value


@pytest.mark.parametrize("field", BOOLEAN_FIELDS)
def test_boolean_flags_reject_non_boolean_values(field):
    for value in (0, 1, "true", None):
        with pytest.raises(ValueError, match=field):
            DiagnosticPlannerPolicy(**{field: value})


def test_invalid_values_are_not_silently_corrected():
    with pytest.raises(ValueError):
        DiagnosticPlannerPolicy(max_steps=-100)


def test_policy_serializes_with_asdict():
    serialized = asdict(DiagnosticPlannerPolicy())
    assert isinstance(serialized, dict)
    assert serialized["max_steps"] == 25


def test_repr_is_deterministic():
    assert repr(DiagnosticPlannerPolicy()) == repr(DiagnosticPlannerPolicy())
    assert "0x" not in repr(DiagnosticPlannerPolicy())


def test_public_import():
    from app.services.diagnostic_engine import DiagnosticPlannerPolicy as PublicPolicy

    assert PublicPolicy is DiagnosticPlannerPolicy


def test_files_are_utf8_without_bom():
    root = Path(__file__).parents[3]
    paths = (
        root / "app/services/diagnostic_engine/planner_policy.py",
        root / "app/services/diagnostic_engine/__init__.py",
        Path(__file__),
    )
    for path in paths:
        content = path.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
