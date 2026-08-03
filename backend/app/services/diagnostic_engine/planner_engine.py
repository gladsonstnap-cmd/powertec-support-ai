"""Deterministic builder for diagnostic plan models."""

from copy import deepcopy
from dataclasses import replace
from typing import Sequence

from app.services.diagnostic_engine.decision_models import Decision, DecisionType
from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.evidence_models import EvidenceResult
from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.memory_models import MemorySnapshot
from app.services.diagnostic_engine.models import DiagnosticContext
from app.services.diagnostic_engine.normalization import normalize_text
from app.services.diagnostic_engine.planner_models import (
    DiagnosticPlan,
    DiagnosticPlanResult,
    DiagnosticPlanStatus,
    PlanCondition,
    PlanStep,
    PlanStepStatus,
    PlanStepType,
)
from app.services.diagnostic_engine.planner_policy import DiagnosticPlannerPolicy


_SENSITIVE_TERMS = (
    "formatar", "apagar", "excluir", "deletar", "remover banco", "limpar banco", "resetar",
    "restaurar fabrica", "firmware", "bios", "regedit", "registro do windows", "certificado digital",
    "certificado fiscal", "nfe", "nfce", "sat", "sefaz", "credenciais", "senha", "producao",
    "banco de dados",
)


class DiagnosticPlannerEngine:
    """Create plans without executing or persisting any diagnostic operation."""

    def __init__(self, policy: DiagnosticPlannerPolicy | None = None) -> None:
        self.policy = policy if policy is not None else DiagnosticPlannerPolicy()

    def build_plan(
        self,
        hypotheses: Sequence[Hypothesis] = (),
        decision: Decision | None = None,
        evidence_result: EvidenceResult | None = None,
        knowledge_result: object | None = None,
        memory_snapshot: MemorySnapshot | None = None,
        previous_plan: DiagnosticPlan | None = None,
        context: DiagnosticContext | None = None,
    ) -> DiagnosticPlanResult:
        original_hypotheses = tuple(hypotheses or ())
        ordered = tuple(sorted(original_hypotheses, key=lambda item: (-item.confidence, item.incident_id)))
        primary = ordered[0] if ordered else None
        if decision is None:
            return self._failure("A decisão atual é necessária para criar o plano.")

        confidence = decision.confidence
        safety_escalation = self._requires_escalation(decision, primary)
        if confidence < self.policy.minimum_plan_confidence and not safety_escalation:
            return self._failure(
                f"A confiança do plano {confidence:.2f} está abaixo do mínimo configurado."
            )

        previous = deepcopy(previous_plan)
        steps = self._preserved_steps(previous)
        reasoning: list[str] = []
        errors: list[str] = []
        incident_id = decision.incident_id or getattr(primary, "incident_id", None)
        risk_level = self._highest_risk(decision.risk_level, getattr(primary, "risk_level", RiskLevel.LOW))
        status = DiagnosticPlanStatus.ACTIVE

        def add_step(step_type: PlanStepType, **kwargs) -> PlanStep | None:
            equivalent = self._equivalent_step(steps, step_type, kwargs)
            if equivalent is not None:
                return equivalent
            if len(steps) >= self.policy.max_steps or not self._within_type_limit(steps, step_type):
                reasoning.append("O limite máximo de passos foi aplicado.")
                return None
            sequence = max((item.sequence for item in steps), default=-1) + 1
            step = PlanStep(
                step_id=f"step-{sequence + 1:03d}-{step_type.value.lower().replace('_', '-')}",
                step_type=step_type,
                status=kwargs.pop("status", PlanStepStatus.READY),
                title=kwargs.pop("title"),
                instruction=kwargs.pop("instruction"),
                sequence=sequence,
                incident_id=incident_id,
                confidence=confidence,
                risk_level=risk_level,
                requires_human=kwargs.pop("requires_human", False),
                requires_confirmation=kwargs.pop("requires_confirmation", False),
                **kwargs,
            )
            steps.append(step)
            return step

        selected: PlanStep | None = None
        kind = decision.decision_type
        sensitive = self._is_sensitive(decision.recommended_action) or self._is_sensitive(decision.recommended_test)

        if safety_escalation or sensitive:
            selected = add_step(
                PlanStepType.ESCALATE_TO_HUMAN,
                title="Encaminhar para atendimento humano",
                instruction="Encaminhar o diagnóstico para análise humana segura.",
                requires_human=True,
            )
            status = DiagnosticPlanStatus.ESCALATED
            reasoning.append(
                "O conteúdo ou risco disponível exige atendimento humano."
                if sensitive else "A hipótese principal ou a decisão exige atendimento humano."
            )
            if not self.policy.stop_after_escalation:
                add_step(
                    PlanStepType.COMPLETE,
                    title="Concluir encaminhamento",
                    instruction="Registrar a conclusão do encaminhamento humano.",
                    status=PlanStepStatus.PENDING,
                    depends_on=(selected.step_id,) if selected else (),
                )
        elif kind == DecisionType.COMPLETE:
            selected = add_step(
                PlanStepType.COMPLETE,
                title="Concluir diagnóstico",
                instruction=decision.completion_reason or decision.message,
            )
            status = DiagnosticPlanStatus.COMPLETED
            reasoning.append("A decisão atual conclui o diagnóstico.")
        elif kind == DecisionType.ASK_QUESTION:
            if decision.next_question:
                selected = add_step(
                    PlanStepType.ASK_QUESTION,
                    title="Solicitar informação",
                    instruction=decision.next_question,
                    question=decision.next_question,
                )
                status = DiagnosticPlanStatus.WAITING_USER
                reasoning.append("A decisão atual solicita uma pergunta ao usuário.")
            else:
                errors.append("A decisão ASK_QUESTION não contém pergunta.")
        elif kind == DecisionType.RUN_TEST:
            if decision.recommended_test and confidence >= self.policy.minimum_step_confidence:
                selected = add_step(
                    PlanStepType.RUN_TEST,
                    title="Realizar teste recomendado",
                    instruction=decision.recommended_test,
                    recommended_test=decision.recommended_test,
                )
                expected = self._expected_results(primary, decision.recommended_test)
                if selected and expected:
                    add_step(
                        PlanStepType.VERIFY_RESULT,
                        title="Verificar resultado do teste",
                        instruction="Comparar o resultado obtido com o critério esperado.",
                        status=PlanStepStatus.BLOCKED,
                        depends_on=(selected.step_id,),
                        success_conditions=tuple(
                            PlanCondition("test_result", "contains", item, f"Resultado esperado: {item}")
                            for item in expected
                        ),
                    )
                reasoning.append(f"O teste recomendado possui confiança {confidence:.2f}.")
            else:
                errors.append("Não há teste seguro com confiança suficiente.")
        elif kind == DecisionType.REQUEST_CONFIRMATION:
            if decision.recommended_action:
                selected = add_step(
                    PlanStepType.REQUEST_CONFIRMATION,
                    title="Solicitar confirmação",
                    instruction=f"Confirmar a ação recomendada: {decision.recommended_action}",
                    recommended_action=decision.recommended_action,
                    requires_confirmation=True,
                    success_conditions=(
                        PlanCondition("user_confirmation", "confirmed", True, "Usuário confirmou a ação."),
                    ),
                )
                status = DiagnosticPlanStatus.WAITING_CONFIRMATION
                reasoning.append("A decisão atual exige confirmação do usuário.")
            else:
                errors.append("A confirmação solicitada não contém ação recomendada.")
        elif kind == DecisionType.RECOMMEND_ACTION:
            if decision.recommended_action and confidence >= self.policy.minimum_step_confidence:
                confirmation = None
                if self._confirmation_required(risk_level):
                    confirmation = add_step(
                        PlanStepType.REQUEST_CONFIRMATION,
                        title="Solicitar confirmação",
                        instruction=f"Confirmar a ação recomendada: {decision.recommended_action}",
                        recommended_action=decision.recommended_action,
                        requires_confirmation=True,
                    )
                selected = add_step(
                    PlanStepType.RECOMMEND_ACTION,
                    title="Recomendar ação",
                    instruction=f"Orientar a ação recomendada, sem executá-la: {decision.recommended_action}",
                    status=PlanStepStatus.BLOCKED if confirmation else PlanStepStatus.READY,
                    recommended_action=decision.recommended_action,
                    requires_confirmation=confirmation is not None,
                    depends_on=(confirmation.step_id,) if confirmation else (),
                )
                status = DiagnosticPlanStatus.WAITING_CONFIRMATION if confirmation else DiagnosticPlanStatus.ACTIVE
                reasoning.append(
                    "A ação sugerida requer confirmação devido ao risco."
                    if confirmation else "A decisão atual recomenda uma ação segura."
                )
            else:
                errors.append("Não há ação segura com confiança suficiente.")
        elif kind == DecisionType.INSUFFICIENT_INFORMATION:
            question = decision.next_question or self._primary_question(primary)
            if question:
                selected = add_step(
                    PlanStepType.ASK_QUESTION,
                    title="Solicitar informação adicional",
                    instruction=question,
                    question=question,
                )
                status = DiagnosticPlanStatus.WAITING_USER
                reasoning.append("As informações são insuficientes; uma pergunta existente foi reutilizada.")
            else:
                selected = add_step(
                    PlanStepType.ESCALATE_TO_HUMAN,
                    title="Encaminhar por informação insuficiente",
                    instruction="Encaminhar o caso para avaliação humana.",
                    requires_human=True,
                )
                status = DiagnosticPlanStatus.ESCALATED
                reasoning.append("Não existe uma pergunta segura disponível; o caso exige avaliação humana.")

        if selected is None and not steps:
            return self._failure(*(errors or ["Não foi possível produzir um plano válido."]), reasoning=reasoning)

        alternatives = self._alternatives(ordered[1:], selected, len(steps))
        current_step_id = selected.step_id if selected is not None else None
        completed = previous.completed_step_ids if previous else ()
        skipped = previous.skipped_step_ids if previous else ()
        failed = previous.failed_step_ids if previous else ()
        metadata = {}
        if self.policy.preserve_metadata:
            metadata = {**(previous.metadata if previous else {}), **deepcopy(decision.metadata)}
        plan = DiagnosticPlan(
            plan_id=previous.plan_id if previous else f"plan-{incident_id or 'unclassified'}",
            status=status if not errors else DiagnosticPlanStatus.FAILED,
            incident_id=incident_id,
            primary_hypothesis_id=getattr(primary, "incident_id", None),
            confidence=confidence,
            steps=tuple(steps[: self.policy.max_steps]),
            current_step_id=current_step_id,
            completed_step_ids=completed,
            skipped_step_ids=skipped,
            failed_step_ids=failed,
            created_from_decision_type=kind,
            requires_human=status == DiagnosticPlanStatus.ESCALATED,
            risk_level=risk_level,
            reasoning=self._limited_reasoning(reasoning),
            metadata=metadata,
            errors=tuple(errors[: self.policy.max_errors]),
        )
        return DiagnosticPlanResult(
            plan=plan,
            success=not errors,
            selected_step=selected,
            alternatives=alternatives,
            reasoning=self._limited_reasoning(reasoning),
            errors=tuple(errors[: self.policy.max_errors]),
            metadata=metadata,
        )

    def _failure(self, *errors: str, reasoning: Sequence[str] = ()) -> DiagnosticPlanResult:
        return DiagnosticPlanResult(
            success=False,
            reasoning=self._limited_reasoning(reasoning),
            errors=tuple(errors[: self.policy.max_errors]),
        )

    def _preserved_steps(self, previous: DiagnosticPlan | None) -> list[PlanStep]:
        if previous is None:
            return []
        terminal = {PlanStepStatus.COMPLETED, PlanStepStatus.SKIPPED, PlanStepStatus.FAILED}
        return [deepcopy(step) for step in previous.steps if step.status in terminal]

    @staticmethod
    def _equivalent_step(steps: Sequence[PlanStep], step_type: PlanStepType, values: dict) -> PlanStep | None:
        for step in steps:
            if (
                step.step_type == step_type
                and step.question == values.get("question")
                and step.recommended_test == values.get("recommended_test")
                and step.recommended_action == values.get("recommended_action")
            ):
                return step
        return None

    def _within_type_limit(self, steps: Sequence[PlanStep], step_type: PlanStepType) -> bool:
        limits = {
            PlanStepType.ASK_QUESTION: self.policy.max_question_steps,
            PlanStepType.RUN_TEST: self.policy.max_test_steps,
            PlanStepType.REQUEST_CONFIRMATION: self.policy.max_confirmation_steps,
            PlanStepType.RECOMMEND_ACTION: self.policy.max_action_steps,
        }
        return sum(step.step_type == step_type for step in steps) < limits.get(step_type, self.policy.max_steps)

    def _alternatives(
        self, hypotheses: Sequence[Hypothesis], selected: PlanStep | None, existing_count: int
    ) -> tuple[PlanStep, ...]:
        if not self.policy.allow_parallel_alternatives:
            return ()
        alternatives = []
        for hypothesis in hypotheses:
            if len(alternatives) >= self.policy.max_parallel_alternatives:
                break
            if hypothesis.confidence < self.policy.minimum_step_confidence:
                continue
            question = self._primary_question(hypothesis)
            if not question:
                continue
            sequence = existing_count + len(alternatives)
            candidate = PlanStep(
                step_id=f"alternative-{sequence + 1:03d}-ask-question-{hypothesis.incident_id}",
                step_type=PlanStepType.ASK_QUESTION,
                status=PlanStepStatus.PENDING,
                title="Investigar hipótese alternativa",
                instruction=question,
                sequence=sequence,
                incident_id=hypothesis.incident_id,
                confidence=hypothesis.confidence,
                risk_level=hypothesis.risk_level,
                requires_human=False,
                requires_confirmation=False,
                question=question,
            )
            if selected is None or candidate.step_id != selected.step_id:
                alternatives.append(candidate)
        return tuple(alternatives)

    def _requires_escalation(self, decision: Decision, hypothesis: Hypothesis | None) -> bool:
        risk = self._highest_risk(decision.risk_level, getattr(hypothesis, "risk_level", RiskLevel.LOW))
        return (
            decision.decision_type == DecisionType.ESCALATE_TO_HUMAN
            or decision.requires_human
            or bool(getattr(hypothesis, "requires_human", False))
            or risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        )

    def _confirmation_required(self, risk: RiskLevel) -> bool:
        return {
            RiskLevel.MEDIUM: self.policy.require_confirmation_for_medium_risk,
            RiskLevel.HIGH: self.policy.require_confirmation_for_high_risk,
            RiskLevel.CRITICAL: self.policy.require_confirmation_for_critical_risk,
        }.get(risk, False)

    @staticmethod
    def _highest_risk(first: RiskLevel, second: RiskLevel) -> RiskLevel:
        order = {RiskLevel.READ_ONLY: 0, RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3, RiskLevel.CRITICAL: 4}
        return max((first, second), key=order.get)

    @staticmethod
    def _primary_question(hypothesis: Hypothesis | None) -> str | None:
        questions = getattr(hypothesis, "next_questions", ()) if hypothesis is not None else ()
        return questions[0].text if questions else None

    @staticmethod
    def _expected_results(hypothesis: Hypothesis | None, recommended: str) -> tuple[str, ...]:
        tests = getattr(hypothesis, "recommended_tests", ()) if hypothesis is not None else ()
        normalized = normalize_text(recommended)
        for diagnostic_test in tests:
            if normalized in {normalize_text(diagnostic_test.id), normalize_text(diagnostic_test.title)}:
                return tuple(diagnostic_test.expected_results)
        return ()

    @staticmethod
    def _is_sensitive(value: str | None) -> bool:
        normalized = normalize_text(value)
        return bool(normalized and any(term in normalized for term in _SENSITIVE_TERMS))

    def _limited_reasoning(self, reasoning: Sequence[str]) -> tuple[str, ...]:
        if not self.policy.preserve_reasoning:
            return ()
        return tuple(reasoning[: self.policy.max_reasoning_messages])
