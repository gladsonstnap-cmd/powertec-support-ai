from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from app.services.diagnostic_engine import MemoryEntry, MemoryFact, MemoryQueryResult, MemorySnapshot


def make_fact(**overrides):
    values = {
        "id": "fact-1",
        "category": "diagnostic",
        "key": "affected_terminal",
        "value": "caixa 2",
        "confidence": 0.8,
        "created_at": 10.5,
        "source": "user",
    }
    values.update(overrides)
    return MemoryFact(**values)


def test_memory_fact_creation():
    fact = make_fact()

    assert fact.id == "fact-1"
    assert fact.category == "diagnostic"
    assert fact.key == "affected_terminal"
    assert fact.value == "caixa 2"
    assert fact.confidence == 0.8
    assert fact.created_at == 10.5
    assert fact.source == "user"


@pytest.mark.parametrize("confidence", [0.0, 0.25, 1.0])
def test_memory_fact_accepts_valid_confidence(confidence):
    assert make_fact(confidence=confidence).confidence == confidence


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_memory_fact_rejects_invalid_confidence(confidence):
    with pytest.raises(ValueError, match="confidence"):
        make_fact(confidence=confidence)


def test_memory_fact_is_immutable():
    fact = make_fact()

    with pytest.raises(FrozenInstanceError):
        fact.key = "changed"


def test_memory_fact_has_value_defensive_copy():
    value = {"terminals": ["caixa 1"]}
    fact = make_fact(value=value)

    value["terminals"].append("caixa 2")

    assert fact.value == {"terminals": ["caixa 1"]}


def test_memory_fact_equality():
    assert make_fact() == make_fact()
    assert make_fact(id="fact-2") != make_fact()


def test_memory_entry_creation_with_defaults():
    entry = MemoryEntry()

    assert entry.facts == ()
    assert entry.hypotheses == ()
    assert entry.evidences == ()
    assert entry.questions == ()
    assert entry.answers == ()


def test_memory_entry_converts_collections_to_tuples():
    fact = make_fact()
    entry = MemoryEntry(
        facts=[fact],
        hypotheses=["hypothesis"],
        evidences=["evidence"],
        questions=["Qual terminal?"],
        answers=["Caixa 2"],
    )

    assert entry.facts == (fact,)
    assert entry.hypotheses == ("hypothesis",)
    assert entry.evidences == ("evidence",)
    assert entry.questions == ("Qual terminal?",)
    assert entry.answers == ("Caixa 2",)


def test_memory_entry_collections_are_defensive_copies():
    facts = [make_fact()]
    questions = ["Qual terminal?"]
    entry = MemoryEntry(facts=facts, questions=questions)

    facts.clear()
    questions.append("Qual erro?")

    assert len(entry.facts) == 1
    assert entry.questions == ("Qual terminal?",)


def test_memory_entry_is_immutable():
    entry = MemoryEntry()

    with pytest.raises(FrozenInstanceError):
        entry.answers = ("resposta",)


def test_memory_entry_equality():
    assert MemoryEntry(facts=(make_fact(),)) == MemoryEntry(facts=(make_fact(),))


def test_memory_snapshot_creation_with_defaults():
    snapshot = MemorySnapshot()

    assert snapshot.entries == ()
    assert snapshot.known_information == {}
    assert snapshot.metadata == {}


def test_memory_snapshot_preserves_entries():
    entry = MemoryEntry(facts=(make_fact(),))
    snapshot = MemorySnapshot(entries=(entry,))

    assert snapshot.entries == (entry,)


def test_memory_snapshot_uses_defensive_copies():
    entries = [MemoryEntry()]
    known_information = {"terminal": {"name": "caixa 2"}}
    metadata = {"origin": {"name": "session"}}
    snapshot = MemorySnapshot(entries=entries, known_information=known_information, metadata=metadata)

    entries.clear()
    known_information["terminal"]["name"] = "changed"
    metadata["origin"]["name"] = "changed"

    assert snapshot.entries == (MemoryEntry(),)
    assert snapshot.known_information == {"terminal": {"name": "caixa 2"}}
    assert snapshot.metadata == {"origin": {"name": "session"}}


def test_memory_snapshot_is_immutable():
    snapshot = MemorySnapshot()

    with pytest.raises(FrozenInstanceError):
        snapshot.entries = (MemoryEntry(),)


def test_memory_snapshot_equality():
    assert MemorySnapshot(metadata={"source": "test"}) == MemorySnapshot(metadata={"source": "test"})


def test_memory_query_result_creation():
    fact = make_fact()
    result = MemoryQueryResult(matches=(fact,), total=3, truncated=True)

    assert result.matches == (fact,)
    assert result.total == 3
    assert result.truncated is True


def test_memory_query_result_converts_matches_to_tuple():
    fact = make_fact()
    result = MemoryQueryResult(matches=[fact], total=1)

    assert result.matches == (fact,)


def test_memory_query_result_rejects_negative_total():
    with pytest.raises(ValueError, match="total"):
        MemoryQueryResult(total=-1)


def test_memory_query_result_is_immutable():
    result = MemoryQueryResult()

    with pytest.raises(FrozenInstanceError):
        result.total = 1


def test_memory_query_result_equality():
    assert MemoryQueryResult(matches=(make_fact(),), total=1) == MemoryQueryResult(matches=(make_fact(),), total=1)


@pytest.mark.parametrize(
    "model",
    [
        make_fact(),
        MemoryEntry(facts=(make_fact(),)),
        MemorySnapshot(entries=(MemoryEntry(),), known_information={"terminal": "caixa 2"}),
        MemoryQueryResult(matches=(make_fact(),), total=1),
    ],
)
def test_models_serialize_with_asdict(model):
    serialized = asdict(model)

    assert isinstance(serialized, dict)
    assert serialized


def test_memory_models_file_is_utf8_without_bom():
    backend_root = Path(__file__).parents[3]
    paths = [
        "app/services/diagnostic_engine/memory_models.py",
        "app/services/diagnostic_engine/__init__.py",
        "tests/services/diagnostic_engine/test_memory_models.py",
    ]
    for path in paths:
        content = (backend_root / path).read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
