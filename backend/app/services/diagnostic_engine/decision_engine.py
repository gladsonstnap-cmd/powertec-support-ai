from dataclasses import replace
from typing import Sequence

from app.services.diagnostic_engine.decision_models import Decision, DecisionInput, DecisionPriority, DecisionType
from app.services.diagnostic_engine.decision_policy import DecisionPolicy
from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.evidence_models import EvidencePolarity, HypothesisUpdate
from app.services.diagnostic_engine.hypothesis_models import Hypothesis
from app.services.diagnostic_engine.knowledge_models import DiagnosticAction, DiagnosticQuestion, DiagnosticTest
from app.services.diagnostic_engine.normalization import normalize_text
from app.services.diagnostic_engine.question_selector import QuestionSelector


BLOCKED_TERMS = (
    "formatar",
    "apagar",
    "excluir",
    "deletar",
    "remover banco",
    "limpar banco",
    "resetar",
    "restaurar fabrica",
    "firmware",
    "bios",
    "registro do windows",
    "regedit",
    "certificado digital",
    "certificado fiscal",
    "nota fiscal",
    "nfe",
    "nfce",
    "sat",
    "sefaz",
    "credenciais",
    "senha",
    "producao",
    "banco de dados",
)

SAFE_TEST_TERMS = (
    "verificar",
    "consultar",
    "conferir",
    "validar",
    "testar conexao",
    "listar",
    "visualizar",
    "coletar log",
    "ler log",
    "ping",
    "status",
    "ler",
    "coletar",
)


class DecisionEngine:
    def __init__(
        self,
        policy: DecisionPolicy | None = None,
        question_selector: QuestionSelector | None = None,
    ) -> None:
        self.policy = policy or DecisionPolicy()
        self.question_selector = question_selector or QuestionSelector()

    def decide(self, input_data: DecisionInput) -> Decision:
        hypotheses = self._normalize_hypotheses(input_data.hypotheses, input_data)
        hypotheses = self._sort_hypotheses(hypotheses)
        top = hypotheses[0] if hypotheses else None
        second = hypotheses[1] if len(hypotheses) > 1 else None
        margin = (top.confidence - second.confidence) if top and second else 1.0
        ambiguous = bool(second and margin < self.policy.ambiguity_margin)

        if not top:
            if input_data.max_questions_reached and input_data.max_tests_reached:
                return self._escalate(None, 0.0, RiskLevel.LOW, ["nao existem hipoteses validas e os limites foram atingidos"])
            return self._insufficient(None, ["nao existem hipoteses validas"])

        unsafe_reason = self._unsafe_reason(top, input_data)
        if top.requires_human:
            return self._escalate(top.incident_id, top.confidence, top.risk_level, ["a hipotese exige atendimento humano"])
        if top.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            priority = DecisionPriority.CRITICAL if top.risk_level == RiskLevel.CRITICAL else DecisionPriority.HIGH
            return self._escalate(top.incident_id, top.confidence, top.risk_level, ["risco da hipotese exige atendimento humano"], priority)
        if unsafe_reason:
            return self._escalate(top.incident_id, top.confidence, top.risk_level, [unsafe_reason])
        if input_data.max_questions_reached and input_data.max_tests_reached and top.confidence < self.policy.action_confidence_threshold:
            return self._escalate(top.incident_id, top.confidence, top.risk_level, ["limites de perguntas e testes atingidos sem confianca suficiente"])

        if (
            top.confidence < self.policy.minimum_hypothesis_confidence
            and not top.missing_information
            and not top.next_questions
        ):
            return self._insufficient(top, ["confianca da melhor hipotese abaixo do limite minimo"])

        question = self._select_question(top, input_data)
        if question and not input_data.max_questions_reached and (
            top.missing_information
            or ambiguous
            or top.confidence < self.policy.test_confidence_threshold
        ):
            return self._ask_question(top, question, ambiguous)

        test = self._select_test(top, input_data.previous_decisions)
        if (
            top.confidence >= self.policy.test_confidence_threshold
            and top.confidence < self.policy.action_confidence_threshold
            and test
            and not input_data.max_tests_reached
        ):
            return self._run_test(top, test)

        action = self._select_action(top, input_data.previous_decisions)
        if action and self._is_blocked_text(f"{action.title} {action.description}"):
            return self._escalate(top.incident_id, top.confidence, top.risk_level, ["acao contem termo sensivel ou destrutivo"])
        if action and top.confidence >= self.policy.action_confidence_threshold:
            if self.policy.require_confirmation_for_actions and input_data.user_confirmation is None:
                return self._request_confirmation(top, action)
            if input_data.user_confirmation is True:
                return self._recommend_action(top, action)

        if self._can_complete(top, input_data):
            return self._complete(top, input_data)

        if question and not input_data.max_questions_reached:
            return self._ask_question(top, question, ambiguous)
        return self._insufficient(top, ["nao ha proximo passo seguro disponivel"])

    def _normalize_hypotheses(self, items: Sequence[Hypothesis | HypothesisUpdate], input_data: DecisionInput) -> list[Hypothesis]:
        by_id = {
            hypothesis.incident_id: hypothesis
            for hypothesis in (input_data.evidence_result.updated_hypotheses if input_data.evidence_result else [])
        }
        hypotheses: list[Hypothesis] = []
        for item in items:
            if isinstance(item, Hypothesis):
                hypotheses.append(item)
            elif isinstance(item, HypothesisUpdate) and item.incident_id in by_id:
                hypotheses.append(by_id[item.incident_id])
        return hypotheses

    def _sort_hypotheses(self, hypotheses: list[Hypothesis]) -> list[Hypothesis]:
        return sorted(hypotheses, key=lambda hypothesis: (-hypothesis.confidence, self._risk_rank(hypothesis.risk_level), hypothesis.incident_id))

    def _select_question(self, hypothesis: Hypothesis, input_data: DecisionInput) -> str | None:
        used = self._used_values(input_data.previous_decisions, "next_question")
        for question in hypothesis.next_questions:
            if normalize_text(question.text) not in used:
                return question.text
        known = input_data.evidence_result.known_information if input_data.evidence_result else {}
        asked = {decision.next_question or "" for decision in input_data.previous_decisions}
        selected = self.question_selector.select_next_question(hypothesis.incident, known_information=known, asked_question_ids=asked)
        if selected and normalize_text(selected.text) not in used:
            return selected.text
        for information in hypothesis.missing_information:
            fallback = f"Confirme a informacao: {information}."
            if normalize_text(fallback) not in used:
                return fallback
        fallback = "Descreva o erro exibido e quais terminais foram afetados."
        return fallback if normalize_text(fallback) not in used else None

    def _select_test(self, hypothesis: Hypothesis, previous_decisions: tuple[Decision, ...]) -> DiagnosticTest | None:
        used = self._used_values(previous_decisions, "recommended_test")
        for test in hypothesis.recommended_tests:
            text = f"{test.title} {test.description}"
            if normalize_text(test.title) in used:
                continue
            if test.risk_level == RiskLevel.READ_ONLY and self._is_safe_test(text):
                return test
        return None

    def _select_action(self, hypothesis: Hypothesis, previous_decisions: tuple[Decision, ...]) -> DiagnosticAction | None:
        used = self._used_values(previous_decisions, "recommended_action")
        for action in hypothesis.recommended_actions:
            if normalize_text(action.title) not in used:
                return action
        return None

    def _can_complete(self, hypothesis: Hypothesis, input_data: DecisionInput) -> bool:
        if hypothesis.confidence < self.policy.completion_confidence_threshold:
            return False
        if hypothesis.missing_information:
            return False
        if self._has_relevant_contradiction(input_data):
            return False
        if hypothesis.requires_human or hypothesis.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            return False
        if hypothesis.recommended_tests or hypothesis.recommended_actions:
            return bool(input_data.diagnostic_context and input_data.diagnostic_context.collected_data.get("solution_confirmed"))
        return True

    def _unsafe_reason(self, hypothesis: Hypothesis, input_data: DecisionInput) -> str | None:
        if self._has_relevant_contradiction(input_data) and hypothesis.risk_level in {RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL}:
            return "contradicao relevante encontrada em contexto de risco"
        return None

    @staticmethod
    def _has_relevant_contradiction(input_data: DecisionInput) -> bool:
        return bool(input_data.evidence_result and input_data.evidence_result.evidence.polarity == EvidencePolarity.CONTRADICTING)

    def _ask_question(self, hypothesis: Hypothesis, question: str, ambiguous: bool) -> Decision:
        reasoning = [f"A hipotese {hypothesis.incident_id} possui confianca {hypothesis.confidence:.2f}."]
        if hypothesis.missing_information:
            reasoning.append("Ainda existem informacoes relevantes nao confirmadas.")
        if ambiguous:
            reasoning.append("A diferenca entre as duas hipoteses principais e inferior ao limite de ambiguidade.")
        return self._decision(
            DecisionType.ASK_QUESTION,
            DecisionPriority.NORMAL,
            "Fazer pergunta",
            question,
            reasoning,
            hypothesis,
            next_question=question,
            metadata={"reason": "question_needed"},
        )

    def _run_test(self, hypothesis: Hypothesis, test: DiagnosticTest) -> Decision:
        return self._decision(
            DecisionType.RUN_TEST,
            DecisionPriority.NORMAL,
            "Recomendar teste diagnostico",
            f"Execute apenas a verificacao: {test.title}.",
            [
                f"A hipotese {hypothesis.incident_id} possui confianca {hypothesis.confidence:.2f}.",
                "O teste selecionado e somente leitura e nao destrutivo.",
            ],
            hypothesis,
            recommended_test=test.title,
            metadata={"test_id": test.id, "tool_name": test.tool_name},
        )

    def _request_confirmation(self, hypothesis: Hypothesis, action: DiagnosticAction) -> Decision:
        return self._decision(
            DecisionType.REQUEST_CONFIRMATION,
            DecisionPriority.HIGH if action.risk_level == RiskLevel.MEDIUM else DecisionPriority.NORMAL,
            "Solicitar confirmacao",
            f"Confirme antes de recomendar a acao: {action.title}.",
            [
                f"A hipotese {hypothesis.incident_id} possui confianca {hypothesis.confidence:.2f}.",
                "A acao sugerida requer confirmacao antes de ser recomendada.",
            ],
            hypothesis,
            recommended_action=action.title,
            confirmation_required=True,
            metadata={"action_id": action.id},
        )

    def _recommend_action(self, hypothesis: Hypothesis, action: DiagnosticAction) -> Decision:
        return self._decision(
            DecisionType.RECOMMEND_ACTION,
            DecisionPriority.NORMAL,
            "Recomendar acao",
            f"Recomende a acao: {action.title}.",
            [
                f"A hipotese {hypothesis.incident_id} possui confianca {hypothesis.confidence:.2f}.",
                "Confirmacao recebida; o motor apenas recomenda e nao executa a acao.",
            ],
            hypothesis,
            recommended_action=action.title,
            metadata={"action_id": action.id},
        )

    def _complete(self, hypothesis: Hypothesis, input_data: DecisionInput) -> Decision:
        return self._decision(
            DecisionType.COMPLETE,
            DecisionPriority.LOW,
            "Concluir diagnostico",
            "O diagnostico pode ser concluido com base nas informacoes confirmadas.",
            [
                f"A hipotese {hypothesis.incident_id} possui confianca {hypothesis.confidence:.2f}.",
                "Nao ha informacao critica ausente nem contradicao relevante.",
            ],
            hypothesis,
            completion_reason="solution_confirmed" if input_data.diagnostic_context else "high_confidence_no_pending_step",
            metadata={"reason": "completion_allowed"},
        )

    def _escalate(
        self,
        incident_id: str | None,
        confidence: float,
        risk_level: RiskLevel,
        reasoning: list[str],
        priority: DecisionPriority = DecisionPriority.HIGH,
    ) -> Decision:
        if risk_level == RiskLevel.CRITICAL:
            priority = DecisionPriority.CRITICAL
        return Decision(
            decision_type=DecisionType.ESCALATE_TO_HUMAN,
            priority=priority,
            title="Escalar para atendimento humano",
            message="Encaminhe o atendimento para um tecnico humano.",
            reasoning=tuple(reasoning),
            confidence=confidence,
            incident_id=incident_id,
            requires_human=True,
            risk_level=risk_level,
            next_question=None,
            recommended_test=None,
            recommended_action=None,
            confirmation_required=False,
            completion_reason=None,
            metadata={"reason": "human_required"},
        )

    def _insufficient(self, hypothesis: Hypothesis | None, reasoning: list[str]) -> Decision:
        return Decision(
            decision_type=DecisionType.INSUFFICIENT_INFORMATION,
            priority=DecisionPriority.NORMAL,
            title="Informacao insuficiente",
            message="Ainda nao ha informacao suficiente para definir o proximo passo com seguranca.",
            reasoning=tuple(reasoning),
            confidence=hypothesis.confidence if hypothesis else 0.0,
            incident_id=hypothesis.incident_id if hypothesis else None,
            requires_human=False,
            risk_level=hypothesis.risk_level if hypothesis else RiskLevel.LOW,
            next_question=None,
            recommended_test=None,
            recommended_action=None,
            confirmation_required=False,
            completion_reason=None,
            metadata={"reason": "insufficient_information"},
        )

    def _decision(
        self,
        decision_type: DecisionType,
        priority: DecisionPriority,
        title: str,
        message: str,
        reasoning: list[str],
        hypothesis: Hypothesis,
        *,
        next_question: str | None = None,
        recommended_test: str | None = None,
        recommended_action: str | None = None,
        confirmation_required: bool = False,
        completion_reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Decision:
        return Decision(
            decision_type=decision_type,
            priority=priority,
            title=title,
            message=message,
            reasoning=tuple(reasoning),
            confidence=hypothesis.confidence,
            incident_id=hypothesis.incident_id,
            requires_human=False,
            risk_level=hypothesis.risk_level,
            next_question=next_question,
            recommended_test=recommended_test,
            recommended_action=recommended_action,
            confirmation_required=confirmation_required,
            completion_reason=completion_reason,
            metadata=metadata or {},
        )

    @staticmethod
    def _used_values(previous_decisions: tuple[Decision, ...], field_name: str) -> set[str]:
        return {
            normalize_text(value)
            for decision in previous_decisions
            if (value := getattr(decision, field_name))
        }

    @staticmethod
    def _is_blocked_text(text: str) -> bool:
        normalized = normalize_text(text)
        return any(term in normalized for term in BLOCKED_TERMS)

    def _is_safe_test(self, text: str) -> bool:
        normalized = normalize_text(text)
        return not self._is_blocked_text(text) and any(term in normalized for term in SAFE_TEST_TERMS)

    @staticmethod
    def _risk_rank(risk_level: RiskLevel) -> int:
        return {
            RiskLevel.READ_ONLY: 0,
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4,
        }[risk_level]
