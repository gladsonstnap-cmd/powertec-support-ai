from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from app.services.diagnostic_engine import DiagnosticMemoryPolicy


def test_default_policy_values():
    policy = DiagnosticMemoryPolicy()

    assert policy.max_entries == 100
    assert policy.max_facts_per_entry == 50
    assert policy.max_query_results == 20
    assert policy.max_known_information_items == 100
    assert policy.minimum_fact_confidence == 0.40
    assert policy.duplicate_confidence_tolerance == 0.05


def test_custom_policy_values():
    policy = DiagnosticMemoryPolicy(
        max_entries=25,
        max_facts_per_entry=10,
        max_query_results=5,
        max_known_information_items=0,
        minimum_fact_confidence=0.75,
        duplicate_confidence_tolerance=0.10,
    )

    assert asdict(policy) | {} == {
        **asdict(DiagnosticMemoryPolicy()),
        "max_entries": 25,
        "max_facts_per_entry": 10,
        "max_query_results": 5,
        "max_known_information_items": 0,
        "minimum_fact_confidence": 0.75,
        "duplicate_confidence_tolerance": 0.10,
    }


def test_policy_is_immutable():
    policy = DiagnosticMemoryPolicy()

    with pytest.raises(FrozenInstanceError):
        policy.max_entries = 200


def test_policy_equality():
    assert DiagnosticMemoryPolicy() == DiagnosticMemoryPolicy()
    assert DiagnosticMemoryPolicy(max_entries=10) != DiagnosticMemoryPolicy()


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("max_entries", 0),
        ("max_entries", -1),
        ("max_facts_per_entry", 0),
        ("max_facts_per_entry", -1),
        ("max_query_results", 0),
        ("max_query_results", -1),
    ],
)
def test_positive_limits_reject_zero_and_negative(field_name, value):
    with pytest.raises(ValueError, match=field_name):
        DiagnosticMemoryPolicy(**{field_name: value})


def test_max_known_information_items_accepts_zero():
    assert DiagnosticMemoryPolicy(max_known_information_items=0).max_known_information_items == 0


def test_max_known_information_items_rejects_negative():
    with pytest.raises(ValueError, match="max_known_information_items"):
        DiagnosticMemoryPolicy(max_known_information_items=-1)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("max_entries", 1.5),
        ("max_facts_per_entry", "50"),
        ("max_query_results", True),
        ("max_known_information_items", False),
    ],
)
def test_integer_limits_reject_non_integers(field_name, value):
    with pytest.raises(ValueError, match=field_name):
        DiagnosticMemoryPolicy(**{field_name: value})


@pytest.mark.parametrize("value", [-0.01, -1.0])
def test_minimum_fact_confidence_rejects_values_below_zero(value):
    with pytest.raises(ValueError, match="minimum_fact_confidence"):
        DiagnosticMemoryPolicy(minimum_fact_confidence=value)


@pytest.mark.parametrize("value", [1.01, 2.0])
def test_minimum_fact_confidence_rejects_values_above_one(value):
    with pytest.raises(ValueError, match="minimum_fact_confidence"):
        DiagnosticMemoryPolicy(minimum_fact_confidence=value)


@pytest.mark.parametrize("value", [-0.01, -1.0])
def test_duplicate_tolerance_rejects_values_below_zero(value):
    with pytest.raises(ValueError, match="duplicate_confidence_tolerance"):
        DiagnosticMemoryPolicy(duplicate_confidence_tolerance=value)


@pytest.mark.parametrize("value", [1.01, 2.0])
def test_duplicate_tolerance_rejects_values_above_one(value):
    with pytest.raises(ValueError, match="duplicate_confidence_tolerance"):
        DiagnosticMemoryPolicy(duplicate_confidence_tolerance=value)


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_minimum_fact_confidence_accepts_exact_boundaries(value):
    assert DiagnosticMemoryPolicy(minimum_fact_confidence=value).minimum_fact_confidence == value


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_duplicate_tolerance_accepts_exact_boundaries(value):
    policy = DiagnosticMemoryPolicy(duplicate_confidence_tolerance=value)

    assert policy.duplicate_confidence_tolerance == value


@pytest.mark.parametrize(
    "field_name",
    [
        "minimum_fact_confidence",
        "duplicate_confidence_tolerance",
    ],
)
@pytest.mark.parametrize("value", ["0.5", None, True])
def test_probability_fields_reject_non_numeric_values(field_name, value):
    with pytest.raises(ValueError, match=field_name):
        DiagnosticMemoryPolicy(**{field_name: value})


def test_default_flags_are_enabled():
    policy = DiagnosticMemoryPolicy()

    assert policy.retain_hypotheses is True
    assert policy.retain_evidences is True
    assert policy.retain_questions is True
    assert policy.retain_answers is True
    assert policy.merge_duplicate_facts is True
    assert policy.prefer_higher_confidence_fact is True
    assert policy.preserve_metadata is True


def test_flags_can_be_disabled():
    policy = DiagnosticMemoryPolicy(
        retain_hypotheses=False,
        retain_evidences=False,
        retain_questions=False,
        retain_answers=False,
        merge_duplicate_facts=False,
        prefer_higher_confidence_fact=False,
        preserve_metadata=False,
    )

    assert all(
        getattr(policy, field_name) is False
        for field_name in (
            "retain_hypotheses",
            "retain_evidences",
            "retain_questions",
            "retain_answers",
            "merge_duplicate_facts",
            "prefer_higher_confidence_fact",
            "preserve_metadata",
        )
    )


def test_policy_construction_has_no_shared_state():
    first = DiagnosticMemoryPolicy()
    second = DiagnosticMemoryPolicy()

    assert first is not second
    assert first == second


def test_public_package_import():
    from app.services import diagnostic_engine

    assert diagnostic_engine.DiagnosticMemoryPolicy is DiagnosticMemoryPolicy


def test_repr_is_deterministic():
    assert repr(DiagnosticMemoryPolicy()) == repr(DiagnosticMemoryPolicy())


def test_policy_serializes_with_asdict():
    serialized = asdict(DiagnosticMemoryPolicy())

    assert serialized["max_entries"] == 100
    assert serialized["preserve_metadata"] is True


def test_policy_files_are_utf8_without_bom():
    backend_root = Path(__file__).parents[3]
    paths = [
        "app/services/diagnostic_engine/memory_policy.py",
        "app/services/diagnostic_engine/__init__.py",
        "tests/services/diagnostic_engine/test_memory_policy.py",
    ]
    for path in paths:
        content = (backend_root / path).read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
