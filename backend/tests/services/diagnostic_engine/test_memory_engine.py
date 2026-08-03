from pathlib import Path

import pytest

from app.services.diagnostic_engine import DiagnosticMemoryEngine
from app.services.diagnostic_engine.memory_models import MemoryEntry, MemoryFact, MemorySnapshot
from app.services.diagnostic_engine.memory_policy import DiagnosticMemoryPolicy


def make_fact(
    id: str = "f1",
    category: str = "device",
    key: str = "status",
    value: object = "offline",
    confidence: float = 0.8,
    created_at: float = 1.0,
    source: str = "user",
) -> MemoryFact:
    return MemoryFact(id, category, key, value, confidence, created_at, source)


def test_engine_uses_default_policy():
    assert DiagnosticMemoryEngine().policy == DiagnosticMemoryPolicy()


def test_engine_accepts_injected_policy():
    policy = DiagnosticMemoryPolicy(max_entries=3)
    assert DiagnosticMemoryEngine(policy).policy is policy


def test_empty_engine_has_no_entries_or_information():
    engine = DiagnosticMemoryEngine()
    assert engine.entries() == ()
    assert engine.known_information() == {}


def test_empty_snapshot_is_complete():
    assert DiagnosticMemoryEngine().snapshot() == MemorySnapshot()


def test_add_entry_stores_and_returns_snapshot():
    entry = MemoryEntry(facts=(make_fact(),))
    result = DiagnosticMemoryEngine().add_entry(entry)
    assert result.entries == (entry,)


def test_entries_returns_tuple():
    engine = DiagnosticMemoryEngine()
    engine.add_entry(MemoryEntry())
    assert isinstance(engine.entries(), tuple)


def test_add_rejects_wrong_type():
    with pytest.raises(TypeError, match="MemoryEntry"):
        DiagnosticMemoryEngine().add_entry("invalid")  # type: ignore[arg-type]


def test_initial_snapshot_is_loaded():
    snapshot = MemorySnapshot((MemoryEntry(facts=(make_fact(),)),), {"site": "A"}, {"turn": 1})
    assert DiagnosticMemoryEngine(initial_snapshot=snapshot).snapshot() == snapshot


def test_initial_snapshot_rejects_wrong_type():
    with pytest.raises(TypeError, match="MemorySnapshot"):
        DiagnosticMemoryEngine(initial_snapshot={})  # type: ignore[arg-type]


def test_initial_snapshot_obeys_entry_limit():
    snapshot = MemorySnapshot(tuple(MemoryEntry(questions=(str(i),)) for i in range(3)))
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(max_entries=2), snapshot)
    assert [entry.questions for entry in engine.entries()] == [("1",), ("2",)]


def test_initial_snapshot_obeys_known_information_limit():
    snapshot = MemorySnapshot(known_information={"a": 1, "b": 2})
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(max_known_information_items=1), snapshot)
    assert engine.known_information() == {"a": 1}


def test_initial_snapshot_obeys_fact_policy():
    snapshot = MemorySnapshot(entries=(MemoryEntry(facts=(make_fact(confidence=0.39),)),))
    engine = DiagnosticMemoryEngine(initial_snapshot=snapshot)
    assert engine.entries()[0].facts == ()


def test_empty_query():
    assert DiagnosticMemoryEngine().query().total == 0


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"key": "status"}, ["f1"]),
        ({"key": "missing"}, []),
        ({"category": "device"}, ["f1"]),
        ({"category": "network"}, []),
        ({"source": "user"}, ["f1"]),
        ({"source": "sensor"}, []),
        ({"minimum_confidence": 0.8}, ["f1"]),
        ({"minimum_confidence": 0.9}, []),
        ({"key": "status", "category": "device", "source": "user"}, ["f1"]),
    ],
)
def test_query_filters(filters, expected):
    engine = DiagnosticMemoryEngine()
    engine.add_entry(MemoryEntry(facts=(make_fact(),)))
    assert [fact.id for fact in engine.query(**filters).matches] == expected


@pytest.mark.parametrize("value", [-0.1, 1.1, "0.5", True, None])
def test_invalid_explicit_minimum_confidence(value):
    kwargs = {"minimum_confidence": value} if value is not None else {"minimum_confidence": None}
    if value is None:
        assert DiagnosticMemoryEngine().query(**kwargs).total == 0
    else:
        with pytest.raises(ValueError):
            DiagnosticMemoryEngine().query(**kwargs)


@pytest.mark.parametrize("value", [0, -1, 1.5, "1", True])
def test_invalid_query_limit(value):
    with pytest.raises(ValueError):
        DiagnosticMemoryEngine().query(limit=value)


def test_query_limit_reports_total_and_truncation():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(merge_duplicate_facts=False))
    engine.add_entry(MemoryEntry(facts=tuple(make_fact(id=str(i), key=str(i)) for i in range(3))))
    result = engine.query(limit=2)
    assert len(result.matches) == 2
    assert result.total == 3
    assert result.truncated is True


def test_query_limit_cannot_exceed_policy_limit():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(max_query_results=1, merge_duplicate_facts=False))
    engine.add_entry(MemoryEntry(facts=(make_fact(key="a"), make_fact(id="f2", key="b"))))
    assert len(engine.query(limit=10).matches) == 1


def test_query_preserves_insertion_order():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(merge_duplicate_facts=False))
    engine.add_entry(MemoryEntry(facts=(make_fact(id="a", key="a"), make_fact(id="b", key="b"))))
    assert [fact.id for fact in engine.query().matches] == ["a", "b"]


def test_minimum_policy_confidence_filters_on_add():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(minimum_fact_confidence=0.7))
    engine.add_entry(MemoryEntry(facts=(make_fact(confidence=0.69),)))
    assert engine.entries()[0].facts == ()


def test_fact_at_minimum_policy_confidence_is_retained():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(minimum_fact_confidence=0.7))
    engine.add_entry(MemoryEntry(facts=(make_fact(confidence=0.7),)))
    assert len(engine.entries()[0].facts) == 1


def test_fact_limit_keeps_first_facts():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(max_facts_per_entry=2, merge_duplicate_facts=False))
    engine.add_entry(MemoryEntry(facts=tuple(make_fact(id=str(i), key=str(i)) for i in range(3))))
    assert [fact.id for fact in engine.entries()[0].facts] == ["0", "1"]


def test_entry_limit_keeps_latest_entries():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(max_entries=2))
    for value in ("a", "b", "c"):
        engine.add_entry(MemoryEntry(questions=(value,)))
    assert [entry.questions[0] for entry in engine.entries()] == ["b", "c"]


def test_known_information_is_stored():
    engine = DiagnosticMemoryEngine()
    engine.add_entry(MemoryEntry(), known_information={"model": "X"})
    assert engine.known_information() == {"model": "X"}


def test_known_information_limit_is_applied():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(max_known_information_items=1))
    engine.add_entry(MemoryEntry(), known_information={"a": 1, "b": 2})
    assert engine.known_information() == {"a": 1}


def test_known_information_zero_limit():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(max_known_information_items=0))
    engine.add_entry(MemoryEntry(), known_information={"a": 1})
    assert engine.known_information() == {}


def test_existing_known_information_can_be_updated_at_limit():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(max_known_information_items=1))
    engine.add_entry(MemoryEntry(), known_information={"a": 1})
    engine.add_entry(MemoryEntry(), known_information={"a": 2, "b": 3})
    assert engine.known_information() == {"a": 2}


def test_metadata_is_preserved_and_merged():
    engine = DiagnosticMemoryEngine()
    engine.add_entry(MemoryEntry(), metadata={"a": 1})
    engine.add_entry(MemoryEntry(), metadata={"b": 2})
    assert engine.snapshot().metadata == {"a": 1, "b": 2}


def test_metadata_is_discarded_by_policy():
    snapshot = MemorySnapshot(metadata={"a": 1})
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(preserve_metadata=False), snapshot)
    engine.add_entry(MemoryEntry(), metadata={"b": 2})
    assert engine.snapshot().metadata == {}


@pytest.mark.parametrize(
    ("policy_field", "entry_field"),
    [
        ("retain_questions", "questions"),
        ("retain_answers", "answers"),
        ("retain_hypotheses", "hypotheses"),
        ("retain_evidences", "evidences"),
    ],
)
def test_retention_policy_can_discard_entry_fields(policy_field, entry_field):
    policy = DiagnosticMemoryPolicy(**{policy_field: False})
    values = {"questions": ("q",), "answers": ("a",)}
    engine = DiagnosticMemoryEngine(policy)
    engine.add_entry(MemoryEntry(**values))
    assert getattr(engine.entries()[0], entry_field) == ()


def test_duplicate_facts_in_one_entry_are_merged():
    engine = DiagnosticMemoryEngine()
    engine.add_entry(MemoryEntry(facts=(make_fact(id="a"), make_fact(id="b", confidence=0.81))))
    assert [fact.id for fact in engine.entries()[0].facts] == ["b"]


def test_duplicate_facts_across_entries_are_merged():
    engine = DiagnosticMemoryEngine()
    engine.add_entry(MemoryEntry(facts=(make_fact(id="a"),)))
    engine.add_entry(MemoryEntry(facts=(make_fact(id="b", confidence=0.81),)))
    assert [fact.id for fact in engine.query().matches] == ["b"]


def test_lower_confidence_duplicate_does_not_replace_existing():
    engine = DiagnosticMemoryEngine()
    engine.add_entry(MemoryEntry(facts=(make_fact(id="high", confidence=0.82),)))
    engine.add_entry(MemoryEntry(facts=(make_fact(id="low", confidence=0.80),)))
    assert [fact.id for fact in engine.query().matches] == ["high"]


@pytest.mark.parametrize("field", ["category", "key", "value", "source"])
def test_different_fact_identity_is_not_deduplicated(field):
    changes = {"category": "network", "key": "mode", "value": "online", "source": "sensor"}
    second = make_fact(id="b", **{field: changes[field]})
    engine = DiagnosticMemoryEngine()
    engine.add_entry(MemoryEntry(facts=(make_fact(id="a"), second)))
    assert len(engine.entries()[0].facts) == 2


def test_confidence_outside_tolerance_is_not_deduplicated():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(duplicate_confidence_tolerance=0.01))
    engine.add_entry(MemoryEntry(facts=(make_fact(confidence=0.8), make_fact(id="b", confidence=0.82))))
    assert len(engine.entries()[0].facts) == 2


def test_deduplication_disabled_preserves_both():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(merge_duplicate_facts=False))
    engine.add_entry(MemoryEntry(facts=(make_fact(), make_fact(id="b"))))
    assert len(engine.entries()[0].facts) == 2


def test_higher_confidence_preference_disabled_preserves_both():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(prefer_higher_confidence_fact=False))
    engine.add_entry(MemoryEntry(facts=(make_fact(), make_fact(id="b", confidence=0.81))))
    assert len(engine.entries()[0].facts) == 2


def test_equivalent_dictionary_values_are_deduplicated_deterministically():
    engine = DiagnosticMemoryEngine()
    engine.add_entry(MemoryEntry(facts=(make_fact(value={"a": 1, "b": 2}), make_fact(id="b", value={"b": 2, "a": 1}))))
    assert len(engine.entries()[0].facts) == 1


def test_add_does_not_mutate_entry_or_mapping_inputs():
    values = {"items": [1]}
    info = {"data": values}
    entry = MemoryEntry(facts=(make_fact(value=values),))
    engine = DiagnosticMemoryEngine()
    engine.add_entry(entry, known_information=info)
    values["items"].append(2)
    assert engine.entries()[0].facts[0].value == {"items": [1]}
    assert engine.known_information() == {"data": {"items": [1]}}


def test_snapshot_is_defensive():
    engine = DiagnosticMemoryEngine()
    engine.add_entry(MemoryEntry(), known_information={"data": [1]})
    snapshot = engine.snapshot()
    snapshot.known_information["data"].append(2)
    assert engine.known_information() == {"data": [1]}


def test_known_information_result_is_defensive():
    engine = DiagnosticMemoryEngine()
    engine.add_entry(MemoryEntry(), known_information={"data": [1]})
    result = engine.known_information()
    result["data"].append(2)
    assert engine.known_information() == {"data": [1]}


def test_clear_removes_all_state_and_is_idempotent():
    engine = DiagnosticMemoryEngine()
    engine.add_entry(MemoryEntry(facts=(make_fact(),)), known_information={"a": 1}, metadata={"b": 2})
    engine.clear()
    engine.clear()
    assert engine.snapshot() == MemorySnapshot()


def test_engines_do_not_share_state():
    first = DiagnosticMemoryEngine()
    second = DiagnosticMemoryEngine()
    first.add_entry(MemoryEntry())
    assert second.entries() == ()


def test_repr_is_deterministic():
    engine = DiagnosticMemoryEngine(DiagnosticMemoryPolicy(max_entries=2))
    expected = "DiagnosticMemoryEngine(entries=0, policy=DiagnosticMemoryPolicy(max_entries=2"
    assert repr(engine).startswith(expected)
    assert "0x" not in repr(engine)


def test_public_import():
    from app.services.diagnostic_engine import DiagnosticMemoryEngine as PublicEngine

    assert PublicEngine is DiagnosticMemoryEngine


def test_files_are_utf8_without_bom():
    root = Path(__file__).parents[3]
    files = (
        root / "app/services/diagnostic_engine/memory_engine.py",
        root / "app/services/diagnostic_engine/__init__.py",
        Path(__file__),
    )
    for file in files:
        content = file.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
