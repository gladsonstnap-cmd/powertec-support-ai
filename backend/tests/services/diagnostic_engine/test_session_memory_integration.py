from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.diagnostic_engine import DiagnosticSessionEngine, DiagnosticSessionStatus
from app.services.diagnostic_engine.decision_models import Decision, DecisionPriority, DecisionType
from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.evidence_models import Evidence, EvidenceResult
from app.services.diagnostic_engine.memory_models import MemoryEntry, MemorySnapshot
from app.services.diagnostic_engine.memory_policy import DiagnosticMemoryPolicy
from app.services.diagnostic_engine.session_models import DiagnosticSession
from app.services.diagnostic_engine.workflow_models import WorkflowResult


def decision(question: str | None = "Qual terminal foi afetado?") -> Decision:
    return Decision(
        decision_type=DecisionType.ASK_QUESTION if question else DecisionType.RUN_TEST,
        priority=DecisionPriority.NORMAL,
        title="Decisão",
        message="Mensagem objetiva.",
        reasoning=("regra determinística",),
        confidence=0.75,
        incident_id="incident-1",
        requires_human=False,
        risk_level=RiskLevel.LOW,
        next_question=question,
        recommended_test=None if question else "Verificar conexão",
        recommended_action=None,
        confirmation_required=False,
        completion_reason=None,
    )


def workflow_result(
    *,
    question: str | None = "Qual terminal foi afetado?",
    known_information: dict[str, object] | None = None,
    success: bool = True,
) -> WorkflowResult:
    if not success:
        return WorkflowResult(success=False, errors=["EVIDENCE: falha controlada"])
    evidence = Evidence.neutral("resposta")
    hypothesis = SimpleNamespace(incident_id="hypothesis-1", confidence=0.5)
    evidence_result = EvidenceResult(
        evidence=evidence,
        updated_hypotheses=[hypothesis],
        hypothesis_updates=[],
        selected_question=None,
        known_information=known_information or {"terminal": "caixa 1"},
        unresolved_information=["erro exibido"],
        evidence_history=[evidence],
    )
    return WorkflowResult(
        intent=SimpleNamespace(intent="INCIDENT"),
        incident=SimpleNamespace(category="NETWORK"),
        hypotheses=[hypothesis],
        evidence_result=evidence_result,
        decision=decision(question),
        success=True,
    )


class FakeWorkflow:
    def __init__(self, *results: WorkflowResult) -> None:
        self.results = list(results or (workflow_result(),))
        self.calls = []

    def run(self, message, **kwargs):
        self.calls.append((message, kwargs))
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


def make_engine(*results, memory_policy=None):
    workflow = FakeWorkflow(*results)
    return DiagnosticSessionEngine(workflow, memory_policy=memory_policy), workflow


def start(subject, message="Sistema não abre"):
    return subject.start_session(message, session_id="session-1").session


def test_session_model_defaults_to_empty_memory_snapshot():
    session = DiagnosticSession("id", DiagnosticSessionStatus.NEW, "erro", "erro")
    assert session.memory_snapshot == MemorySnapshot()


def test_memory_defaults_are_not_shared():
    first = DiagnosticSession("1", DiagnosticSessionStatus.NEW, "erro", "erro")
    second = DiagnosticSession("2", DiagnosticSessionStatus.NEW, "erro", "erro")
    assert first.memory_snapshot is not second.memory_snapshot


def test_first_interaction_creates_memory_entry():
    subject, _ = make_engine()
    assert len(start(subject).memory_snapshot.entries) == 1


def test_original_message_is_recorded_as_session_fact():
    subject, _ = make_engine()
    fact = start(subject).memory_snapshot.entries[0].facts[0]
    assert (fact.category, fact.key, fact.value) == ("session", "original_message", "Sistema não abre")


def test_continuation_preserves_and_adds_entries():
    subject, _ = make_engine(workflow_result(), workflow_result(question=None))
    first = start(subject)
    second = subject.continue_session(first, "Somente o caixa 1").session
    assert len(second.memory_snapshot.entries) == 2
    assert second.memory_snapshot.entries[0] == first.memory_snapshot.entries[0]


def test_known_information_is_updated_in_memory():
    subject, _ = make_engine()
    session = start(subject)
    assert session.memory_snapshot.known_information == {"terminal": "caixa 1"}
    assert session.known_information == session.memory_snapshot.known_information


def test_memory_known_information_is_forwarded_to_workflow():
    subject, workflow = make_engine(workflow_result(), workflow_result(question=None))
    first = start(subject)
    subject.continue_session(first, "resposta")
    assert workflow.calls[1][1]["known_information"] == {"terminal": "caixa 1"}


def test_hypotheses_are_stored_only_as_hypotheses():
    subject, _ = make_engine()
    entry = start(subject).memory_snapshot.entries[0]
    assert entry.hypotheses
    assert all(fact.key != "hypothesis" for fact in entry.facts)


def test_current_evidence_is_stored_as_evidence():
    subject, _ = make_engine()
    entry = start(subject).memory_snapshot.entries[0]
    assert len(entry.evidences) == 1
    assert entry.evidences[0].raw_text == "resposta"


def test_question_is_stored():
    subject, _ = make_engine()
    assert start(subject).memory_snapshot.entries[0].questions == ("Qual terminal foi afetado?",)


def test_answer_is_stored_on_continuation():
    subject, _ = make_engine(workflow_result(), workflow_result(question=None))
    session = start(subject)
    continued = subject.continue_session(session, "Caixa 2").session
    assert continued.memory_snapshot.entries[-1].answers == ("Caixa 2",)


def test_start_message_is_not_stored_as_answer():
    subject, _ = make_engine()
    assert start(subject).memory_snapshot.entries[0].answers == ()


def test_previous_snapshot_is_not_mutated():
    subject, _ = make_engine(workflow_result(), workflow_result(question=None))
    first = start(subject)
    snapshot = deepcopy(first.memory_snapshot)
    subject.continue_session(first, "Caixa 2")
    assert first.memory_snapshot == snapshot


def test_previous_session_is_not_mutated():
    subject, _ = make_engine(workflow_result(), workflow_result(question=None))
    first = start(subject)
    snapshot = deepcopy(first)
    subject.continue_session(first, "Caixa 2")
    assert first == snapshot


def test_duplicate_known_fact_is_not_repeated():
    subject, _ = make_engine(workflow_result(), workflow_result(question=None))
    continued = subject.continue_session(start(subject), "Caixa 2").session
    terminal_facts = [fact for entry in continued.memory_snapshot.entries for fact in entry.facts if fact.key == "terminal"]
    assert len(terminal_facts) == 1


def test_deduplication_can_be_disabled():
    policy = DiagnosticMemoryPolicy(merge_duplicate_facts=False)
    subject, _ = make_engine(workflow_result(), workflow_result(question=None), memory_policy=policy)
    continued = subject.continue_session(start(subject), "Caixa 2").session
    terminal_facts = [fact for entry in continued.memory_snapshot.entries for fact in entry.facts if fact.key == "terminal"]
    assert len(terminal_facts) == 2


def test_entry_limit_is_applied():
    policy = DiagnosticMemoryPolicy(max_entries=1)
    subject, _ = make_engine(workflow_result(), workflow_result(question=None), memory_policy=policy)
    continued = subject.continue_session(start(subject), "Caixa 2").session
    assert len(continued.memory_snapshot.entries) == 1


def test_fact_limit_is_applied():
    policy = DiagnosticMemoryPolicy(max_facts_per_entry=1)
    subject, _ = make_engine(memory_policy=policy)
    assert len(start(subject).memory_snapshot.entries[0].facts) == 1


def test_minimum_confidence_boundary_is_respected():
    policy = DiagnosticMemoryPolicy(minimum_fact_confidence=1.0)
    subject, _ = make_engine(memory_policy=policy)
    assert all(fact.confidence == 1.0 for fact in start(subject).memory_snapshot.entries[0].facts)


@pytest.mark.parametrize(
    ("policy", "field"),
    [
        (DiagnosticMemoryPolicy(retain_hypotheses=False), "hypotheses"),
        (DiagnosticMemoryPolicy(retain_evidences=False), "evidences"),
        (DiagnosticMemoryPolicy(retain_questions=False), "questions"),
        (DiagnosticMemoryPolicy(retain_answers=False), "answers"),
    ],
)
def test_retention_flags_are_applied(policy, field):
    subject, _ = make_engine(workflow_result(), workflow_result(question=None), memory_policy=policy)
    session = start(subject)
    if field == "answers":
        session = subject.continue_session(session, "Caixa 2").session
    assert getattr(session.memory_snapshot.entries[-1], field) == ()


def test_existing_memory_metadata_is_preserved():
    subject, _ = make_engine(workflow_result(question=None))
    session = start(subject)
    with_metadata = replace(session, memory_snapshot=MemorySnapshot(session.memory_snapshot.entries, session.memory_snapshot.known_information, {"origin": "test"}))
    continued = subject.continue_session(with_metadata, "Caixa 2").session
    assert continued.memory_snapshot.metadata == {"origin": "test"}


def test_metadata_is_removed_when_policy_disables_preservation():
    policy = DiagnosticMemoryPolicy(preserve_metadata=False)
    subject, _ = make_engine(workflow_result(question=None), memory_policy=policy)
    session = start(subject)
    with_metadata = replace(session, memory_snapshot=MemorySnapshot(session.memory_snapshot.entries, {}, {"origin": "test"}))
    assert subject.continue_session(with_metadata, "Caixa 2").session.memory_snapshot.metadata == {}


def test_status_does_not_change_memory():
    subject, _ = make_engine()
    session = start(subject)
    assert subject.continue_session(session, "status").session.memory_snapshot == session.memory_snapshot


def test_cancel_preserves_memory():
    subject, _ = make_engine()
    session = start(subject)
    assert subject.continue_session(session, "cancelar").session.memory_snapshot == session.memory_snapshot


def test_escalate_preserves_memory_and_does_not_create_false_fact():
    subject, _ = make_engine()
    session = start(subject)
    escalated = subject.continue_session(session, "humano").session
    assert escalated.memory_snapshot == session.memory_snapshot
    assert all(fact.value != "humano" for entry in escalated.memory_snapshot.entries for fact in entry.facts)


def test_restart_discards_previous_memory():
    subject, _ = make_engine()
    session = start(subject)
    restarted = subject.continue_session(session, "reiniciar").session
    assert len(restarted.memory_snapshot.entries) == 1
    assert restarted.memory_snapshot.entries[0].facts[0].key == "original_message"


@pytest.mark.parametrize("message", ["", "   ", None])
def test_empty_message_is_rejected(message):
    subject, _ = make_engine()
    with pytest.raises(ValueError, match="message"):
        subject.start_session(message)


def test_workflow_error_does_not_change_existing_memory():
    subject, _ = make_engine(workflow_result(question=None), workflow_result(success=False))
    session = start(subject)
    continued = subject.continue_session(session, "Caixa 2").session
    assert continued.memory_snapshot == session.memory_snapshot


def test_custom_policy_is_injected():
    policy = DiagnosticMemoryPolicy(max_entries=2)
    subject, _ = make_engine(memory_policy=policy)
    assert subject.memory_policy is policy


def test_default_constructor_builds_memory_policy():
    assert isinstance(DiagnosticSessionEngine().memory_policy, DiagnosticMemoryPolicy)


def test_start_is_deterministic_with_supplied_id(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.session_engine.time.monotonic", lambda: 10.0)
    first, _ = make_engine()
    second, _ = make_engine()
    assert start(first) == start(second)


def test_continue_is_deterministic(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.session_engine.time.monotonic", lambda: 10.0)
    first, _ = make_engine(workflow_result(), workflow_result(question=None))
    second, _ = make_engine(workflow_result(), workflow_result(question=None))
    assert first.continue_session(start(first), "Caixa 2").session == second.continue_session(start(second), "Caixa 2").session


def test_session_snapshot_is_a_defensive_copy():
    source = MemorySnapshot(entries=(MemoryEntry(),), known_information={"nested": [1]})
    session = DiagnosticSession("id", DiagnosticSessionStatus.NEW, "erro", "erro", memory_snapshot=source)
    source.known_information["nested"].append(2)
    assert session.memory_snapshot.known_information == {"nested": [1]}


def test_changed_files_are_utf8_without_bom():
    root = Path(__file__).parents[3]
    paths = (
        root / "app/services/diagnostic_engine/session_models.py",
        root / "app/services/diagnostic_engine/session_engine.py",
        Path(__file__),
    )
    for path in paths:
        content = path.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
