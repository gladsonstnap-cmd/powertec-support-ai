import time
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.diagnostic_engine.decision_engine import DecisionEngine
from app.services.diagnostic_engine.decision_models import Decision, DecisionInput
from app.services.diagnostic_engine.evidence_engine import EvidenceEngine
from app.services.diagnostic_engine.evidence_models import Evidence
from app.services.diagnostic_engine.hypothesis_engine import HypothesisEngine
from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.incident_classifier import IncidentClassifier
from app.services.diagnostic_engine.intent_classifier import IntentClassifier
from app.services.diagnostic_engine.knowledge_base import KnowledgeBase
from app.services.diagnostic_engine.models import DiagnosticContext
from app.services.diagnostic_engine.workflow_models import WorkflowResult, WorkflowStep


class DiagnosticWorkflowEngine:
    """Orchestrates the deterministic diagnostic components in a fixed order."""

    def __init__(
        self,
        intent_classifier: IntentClassifier | None = None,
        incident_classifier: IncidentClassifier | None = None,
        knowledge_base: KnowledgeBase | None = None,
        hypothesis_engine: HypothesisEngine | None = None,
        evidence_engine: EvidenceEngine | None = None,
        decision_engine: DecisionEngine | None = None,
    ) -> None:
        self.intent_classifier = intent_classifier if intent_classifier is not None else IntentClassifier()
        self.incident_classifier = incident_classifier if incident_classifier is not None else IncidentClassifier()
        self.knowledge_base = knowledge_base if knowledge_base is not None else KnowledgeBase.load_default()
        self.hypothesis_engine = (
            hypothesis_engine if hypothesis_engine is not None else HypothesisEngine(knowledge_base=self.knowledge_base)
        )
        self.evidence_engine = (
            evidence_engine if evidence_engine is not None else EvidenceEngine(knowledge_base=self.knowledge_base)
        )
        self.decision_engine = decision_engine if decision_engine is not None else DecisionEngine()

    def run(
        self,
        message: str,
        context: DiagnosticContext | None = None,
        history: Mapping[str, Any] | Sequence[Decision] | None = None,
        user_confirmation: bool | None = None,
        previous_hypotheses: Sequence[Hypothesis] | None = None,
        previous_evidence: Sequence[Evidence] | None = None,
        previous_decisions: Sequence[Decision] | None = None,
        questions_asked: Sequence[str] | None = None,
        known_information: Mapping[str, object] | None = None,
    ) -> WorkflowResult:
        started_at = time.monotonic()
        result = WorkflowResult(
            hypotheses=[],
            metadata={
                "failed_step": None,
                "has_context": context is not None,
                "has_history": history is not None,
                "user_confirmation": user_confirmation,
            },
        )

        try:
            result.steps_executed.append(WorkflowStep.INTENT)
            result.intent = self.intent_classifier.classify(message)

            result.steps_executed.append(WorkflowStep.INCIDENT)
            result.incident = self.incident_classifier.classify(message, context)

            result.steps_executed.append(WorkflowStep.KNOWLEDGE)
            result.knowledge_result = self.knowledge_base.search(
                message,
                category=result.incident.category,
            )

            known_values = dict(
                known_information
                if known_information is not None
                else self._history_value(history, "known_information", {})
            )
            asked_question_ids = set(
                questions_asked
                if questions_asked is not None
                else self._history_value(history, "asked_question_ids", set())
            )
            evidence_history = list(
                previous_evidence
                if previous_evidence is not None
                else self._history_value(history, "evidence_history", [])
            )
            decision_history = tuple(
                previous_decisions if previous_decisions is not None else self._previous_decisions(history)
            )

            result.steps_executed.append(WorkflowStep.HYPOTHESIS)
            if previous_hypotheses is None:
                result.hypotheses = self.hypothesis_engine.generate(
                    message,
                    result.incident.category,
                    known_information=known_values,
                    asked_question_ids=asked_question_ids,
                )
            else:
                result.hypotheses = list(previous_hypotheses)

            result.steps_executed.append(WorkflowStep.EVIDENCE)
            result.evidence_result = self.evidence_engine.apply(
                result.hypotheses,
                message,
                asked_question_ids=asked_question_ids,
                known_information=known_values,
                evidence_history=evidence_history,
            )

            result.steps_executed.append(WorkflowStep.DECISION)
            result.decision = self.decision_engine.decide(
                DecisionInput(
                    hypotheses=result.evidence_result.updated_hypotheses,
                    evidence_result=result.evidence_result,
                    diagnostic_context=context,
                    previous_decisions=decision_history,
                    user_confirmation=user_confirmation,
                )
            )

            result.steps_executed.append(WorkflowStep.COMPLETE)
            result.success = True
        except Exception as exc:  # The workflow boundary converts component failures into data.
            failed_step = result.steps_executed[-1] if result.steps_executed else None
            result.metadata["failed_step"] = failed_step
            step_name = failed_step.value if failed_step else "UNKNOWN"
            result.errors.append(f"{step_name}: {type(exc).__name__}: {exc}")
        finally:
            result.processing_time_ms = max(0.0, (time.monotonic() - started_at) * 1000.0)

        return result

    @staticmethod
    def _history_value(history: Mapping[str, Any] | Sequence[Decision] | None, key: str, default: Any) -> Any:
        if isinstance(history, Mapping):
            value = history.get(key, default)
            return default if value is None else value
        return default

    @staticmethod
    def _previous_decisions(history: Mapping[str, Any] | Sequence[Decision] | None) -> tuple[Decision, ...]:
        if history is None:
            return ()
        if isinstance(history, Mapping):
            return tuple(history.get("previous_decisions") or ())
        return tuple(history)
