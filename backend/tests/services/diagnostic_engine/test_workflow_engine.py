from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.diagnostic_engine import DiagnosticWorkflowEngine, WorkflowResult, WorkflowStep
from app.services.diagnostic_engine.decision_engine import DecisionEngine
from app.services.diagnostic_engine.evidence_engine import EvidenceEngine
from app.services.diagnostic_engine.hypothesis_engine import HypothesisEngine
from app.services.diagnostic_engine.incident_classifier import IncidentClassifier
from app.services.diagnostic_engine.intent_classifier import IntentClassifier
from app.services.diagnostic_engine.knowledge_base import KnowledgeBase
from app.services.diagnostic_engine.models import DiagnosticContext


class StubIntent:
    def classify(self, message):
        return ("intent", message)


class StubIncident:
    def classify(self, message, context=None):
        return SimpleNamespace(category="CATEGORY", message=message, context=context)


class StubKnowledge:
    def search(self, message, *, category=None):
        return [(message, category)]


class StubHypothesis:
    def generate(self, message, category, **kwargs):
        return [SimpleNamespace(incident_id="hypothesis", confidence=0.5, kwargs=kwargs)]


class StubEvidence:
    def apply(self, hypotheses, raw_text, **kwargs):
        return SimpleNamespace(updated_hypotheses=hypotheses, hypotheses=hypotheses, raw_text=raw_text, kwargs=kwargs)


class StubDecision:
    def decide(self, input_data):
        return SimpleNamespace(kind="decision", input_data=input_data)


def make_engine(**overrides):
    components = {
        "intent_classifier": StubIntent(),
        "incident_classifier": StubIncident(),
        "knowledge_base": StubKnowledge(),
        "hypothesis_engine": StubHypothesis(),
        "evidence_engine": StubEvidence(),
        "decision_engine": StubDecision(),
    }
    components.update(overrides)
    return DiagnosticWorkflowEngine(**components)


def test_complete_flow_runs_every_step_in_order():
    result = make_engine().run("sistema não abre")

    assert result.success is True
    assert result.steps_executed == list(WorkflowStep)


class FailingComponent:
    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise RuntimeError("falha controlada")

        return fail


@pytest.mark.parametrize(
    ("dependency", "step"),
    [
        ("intent_classifier", WorkflowStep.INTENT),
        ("incident_classifier", WorkflowStep.INCIDENT),
        ("knowledge_base", WorkflowStep.KNOWLEDGE),
        ("hypothesis_engine", WorkflowStep.HYPOTHESIS),
        ("evidence_engine", WorkflowStep.EVIDENCE),
        ("decision_engine", WorkflowStep.DECISION),
    ],
)
def test_component_failure_is_captured(dependency, step):
    result = make_engine(**{dependency: FailingComponent()}).run("mensagem")

    assert result.success is False
    assert result.steps_executed[-1] == step
    assert result.metadata["failed_step"] == step
    assert result.errors == [f"{step.value}: RuntimeError: falha controlada"]


def test_workflow_result_is_filled():
    result = make_engine().run("mensagem")

    assert isinstance(result, WorkflowResult)
    assert result.intent is not None
    assert result.incident is not None
    assert result.knowledge_result is not None
    assert result.hypotheses
    assert result.evidence_result is not None
    assert result.decision is not None
    assert result.errors == []


def test_processing_time_is_measured(monkeypatch):
    values = iter((10.0, 10.125))
    monkeypatch.setattr("app.services.diagnostic_engine.workflow_engine.time.monotonic", lambda: next(values))

    assert make_engine().run("mensagem").processing_time_ms == pytest.approx(125.0)


def test_deterministic_outputs():
    engine = make_engine()
    first = engine.run("mensagem")
    second = engine.run("mensagem")

    for field in ("intent", "knowledge_result", "hypotheses", "success", "errors", "steps_executed", "metadata"):
        assert getattr(first, field) == getattr(second, field)


def test_dependency_injection_keeps_supplied_instances():
    dependencies = {
        "intent_classifier": StubIntent(),
        "incident_classifier": StubIncident(),
        "knowledge_base": StubKnowledge(),
        "hypothesis_engine": StubHypothesis(),
        "evidence_engine": StubEvidence(),
        "decision_engine": StubDecision(),
    }
    engine = DiagnosticWorkflowEngine(**dependencies)

    for name, component in dependencies.items():
        assert getattr(engine, name) is component


def test_default_constructor_builds_all_components():
    engine = DiagnosticWorkflowEngine()

    assert isinstance(engine.intent_classifier, IntentClassifier)
    assert isinstance(engine.incident_classifier, IncidentClassifier)
    assert isinstance(engine.knowledge_base, KnowledgeBase)
    assert isinstance(engine.hypothesis_engine, HypothesisEngine)
    assert isinstance(engine.evidence_engine, EvidenceEngine)
    assert isinstance(engine.decision_engine, DecisionEngine)


def test_history_is_forwarded_without_mutation():
    previous = SimpleNamespace(next_question=None, recommended_test=None, recommended_action=None)
    history = {
        "known_information": {"terminal": "caixa 2"},
        "asked_question_ids": {"question-1"},
        "evidence_history": ["evidence-1"],
        "previous_decisions": [previous],
    }
    snapshot = deepcopy(history)

    result = make_engine().run("mensagem", history=history)

    assert result.hypotheses[0].kwargs["known_information"] == history["known_information"]
    assert result.evidence_result.kwargs["evidence_history"] == history["evidence_history"]
    assert result.decision.input_data.previous_decisions == (previous,)
    assert history == snapshot


def test_user_confirmation_is_forwarded():
    result = make_engine().run("mensagem", user_confirmation=True)

    assert result.decision.input_data.user_confirmation is True
    assert result.metadata["user_confirmation"] is True


def test_without_history_uses_empty_values():
    result = make_engine().run("mensagem")

    assert result.hypotheses[0].kwargs["known_information"] == {}
    assert result.evidence_result.kwargs["evidence_history"] == []
    assert result.decision.input_data.previous_decisions == ()


def test_without_confirmation_uses_none():
    result = make_engine().run("mensagem")

    assert result.decision.input_data.user_confirmation is None


def test_success_true_has_complete_step():
    result = make_engine().run("mensagem")

    assert result.success is True
    assert result.steps_executed[-1] == WorkflowStep.COMPLETE


def test_success_false_does_not_have_complete_step():
    result = make_engine(intent_classifier=FailingComponent()).run("mensagem")

    assert result.success is False
    assert WorkflowStep.COMPLETE not in result.steps_executed


def test_inputs_are_not_changed():
    context = DiagnosticContext(message="mensagem", collected_data={"scope": "caixa"})
    history = {"known_information": {"scope": "caixa"}, "asked_question_ids": {"q1"}}
    context_snapshot = deepcopy(context)
    history_snapshot = deepcopy(history)

    make_engine().run("mensagem", context=context, history=history, user_confirmation=False)

    assert context == context_snapshot
    assert history == history_snapshot


def test_created_and_modified_files_are_utf8_without_bom():
    paths = [
        "app/services/diagnostic_engine/workflow_models.py",
        "app/services/diagnostic_engine/workflow_engine.py",
        "app/services/diagnostic_engine/__init__.py",
        "tests/services/diagnostic_engine/test_workflow_engine.py",
    ]
    for path in paths:
        content = open(path, "rb").read()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
