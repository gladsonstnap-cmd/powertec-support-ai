import time
from dataclasses import replace
from uuid import uuid4

from app.services.diagnostic_engine.decision_models import Decision, DecisionType
from app.services.diagnostic_engine.normalization import normalize_text
from app.services.diagnostic_engine.models import DiagnosticContext
from app.services.diagnostic_engine.memory_engine import DiagnosticMemoryEngine
from app.services.diagnostic_engine.memory_models import MemoryEntry, MemoryFact, MemorySnapshot
from app.services.diagnostic_engine.memory_policy import DiagnosticMemoryPolicy
from app.services.diagnostic_engine.planner_engine import DiagnosticPlannerEngine
from app.services.diagnostic_engine.planner_models import DiagnosticPlanResult
from app.services.diagnostic_engine.session_models import (
    DiagnosticSession,
    DiagnosticSessionStatus,
    SessionTurnResult,
)
from app.services.diagnostic_engine.session_policy import DiagnosticSessionPolicy
from app.services.diagnostic_engine.workflow_engine import DiagnosticWorkflowEngine
from app.services.diagnostic_engine.workflow_models import WorkflowResult


_CANCEL_COMMANDS = {"cancelar", "encerrar"}
_RESTART_COMMANDS = {"reiniciar", "comecar novamente"}
_STATUS_COMMANDS = {"status"}
_HUMAN_COMMANDS = {"atendente", "humano"}


class DiagnosticSessionEngine:
    """Stateless coordinator that returns a new session snapshot per turn."""

    def __init__(
        self,
        workflow_engine: DiagnosticWorkflowEngine | None = None,
        policy: DiagnosticSessionPolicy | None = None,
        memory_policy: DiagnosticMemoryPolicy | None = None,
        planner_engine: DiagnosticPlannerEngine | None = None,
    ) -> None:
        self.workflow_engine = workflow_engine if workflow_engine is not None else DiagnosticWorkflowEngine()
        self.policy = policy if policy is not None else DiagnosticSessionPolicy()
        self.memory_policy = memory_policy if memory_policy is not None else DiagnosticMemoryPolicy()
        self.planner_engine = planner_engine if planner_engine is not None else DiagnosticPlannerEngine()

    def start_session(
        self,
        message: str,
        session_id: str | None = None,
        context: DiagnosticContext | None = None,
    ) -> SessionTurnResult:
        self._validate_message(message)
        if session_id is not None and not session_id.strip():
            raise ValueError("session_id must not be empty")

        now = time.monotonic()
        initial = DiagnosticSession(
            session_id=session_id.strip() if session_id is not None else str(uuid4()),
            status=DiagnosticSessionStatus.NEW,
            original_message=message,
            last_message=message,
            created_at_monotonic=now,
            updated_at_monotonic=now,
            metadata={"session_id_generated": session_id is None},
            memory_snapshot=MemorySnapshot(),
        )
        workflow_result = self.workflow_engine.run(message, context=context)
        return self._apply_workflow(initial, message, workflow_result, context=context, is_initial=True)

    def continue_session(
        self,
        session: DiagnosticSession,
        message: str,
        context: DiagnosticContext | None = None,
        user_confirmation: bool | None = None,
    ) -> SessionTurnResult:
        self._validate_message(message)
        blocked = self._blocked_terminal_result(session)
        if blocked is not None:
            return blocked

        command = normalize_text(message)
        if command in _CANCEL_COMMANDS:
            return self.cancel_session(session, reason="comando do usuario")
        if command in _RESTART_COMMANDS:
            return self.restart_session(session, message, context=context)
        if command in _STATUS_COMMANDS:
            return self._status_result(session)
        if command in _HUMAN_COMMANDS:
            return self._manual_escalation(session, message, "atendimento humano solicitado")

        if session.interaction_count >= self.policy.max_interactions:
            return self._manual_escalation(session, message, "limite de interacoes atingido")
        if self._is_repeated_answer(session, message):
            return self._manual_escalation(session, message, "limite de respostas repetidas atingido")

        questions_asked = session.questions_asked
        if session.current_question and session.current_question not in questions_asked:
            questions_asked = (*questions_asked, session.current_question)

        memory = DiagnosticMemoryEngine(self.memory_policy, session.memory_snapshot)
        workflow_result = self.workflow_engine.run(
            message,
            context=context,
            user_confirmation=user_confirmation,
            previous_hypotheses=session.hypotheses,
            previous_evidence=session.evidence_history,
            previous_decisions=session.decisions,
            questions_asked=questions_asked,
            known_information=memory.known_information(),
        )
        return self._apply_workflow(
            session,
            message,
            workflow_result,
            context=context,
            user_confirmation=user_confirmation,
            questions_asked=questions_asked,
            is_initial=False,
        )

    def cancel_session(self, session: DiagnosticSession, reason: str | None = None) -> SessionTurnResult:
        if session.status == DiagnosticSessionStatus.CANCELLED:
            return self._unchanged_result(session, "A sessão já está cancelada.", "session already cancelled")
        now = time.monotonic()
        metadata = {**session.metadata, "terminal_reason": reason or "sessao cancelada"}
        updated = replace(
            session,
            status=DiagnosticSessionStatus.CANCELLED,
            current_question=None,
            updated_at_monotonic=now,
            metadata=metadata,
        )
        return self._turn(updated, None, "Sessão de diagnóstico cancelada.", session.status, True)

    def restart_session(
        self,
        session: DiagnosticSession,
        message: str,
        context: DiagnosticContext | None = None,
    ) -> SessionTurnResult:
        if session.status == DiagnosticSessionStatus.COMPLETED and not self.policy.allow_restart_after_completion:
            return self._unchanged_result(session, "A sessão concluída não pode ser reiniciada.", "restart not allowed")
        restart_message = message
        if normalize_text(message) in _RESTART_COMMANDS:
            restart_message = session.original_message
        return self.start_session(restart_message, session_id=session.session_id, context=context)

    def _apply_workflow(
        self,
        session: DiagnosticSession,
        message: str,
        workflow_result: WorkflowResult,
        *,
        context: DiagnosticContext | None,
        user_confirmation: bool | None = None,
        questions_asked: tuple[str, ...] | None = None,
        is_initial: bool,
    ) -> SessionTurnResult:
        now = time.monotonic()
        previous_status = session.status
        errors = tuple(workflow_result.errors)
        decision = workflow_result.decision
        status = self._status_for(workflow_result)
        current_question = decision.next_question if decision else None
        metadata = dict(session.metadata)

        if not workflow_result.success:
            metadata["terminal_reason"] = "workflow failure"
        elif current_question and normalize_text(current_question) in {
            normalize_text(question) for question in (questions_asked or session.questions_asked)
        }:
            status = DiagnosticSessionStatus.ESCALATED
            current_question = None
            metadata["terminal_reason"] = "repeated question prevented"
        elif decision and decision.decision_type == DecisionType.ASK_QUESTION:
            if len(questions_asked or session.questions_asked) >= self.policy.max_questions:
                status = DiagnosticSessionStatus.ESCALATED
                current_question = None
                metadata["terminal_reason"] = "question limit reached"
        elif decision and decision.decision_type == DecisionType.RUN_TEST:
            test_count = sum(item.decision_type == DecisionType.RUN_TEST for item in session.decisions)
            if test_count >= self.policy.max_tests:
                status = DiagnosticSessionStatus.ESCALATED
                metadata["terminal_reason"] = "test limit reached"

        evidence_result = workflow_result.evidence_result
        evidence_history = self._dedupe_evidence(
            (*session.evidence_history, *(evidence_result.evidence_history if evidence_result else ()))
        )
        hypotheses = tuple(
            evidence_result.updated_hypotheses
            if evidence_result is not None
            else workflow_result.hypotheses or session.hypotheses
        )
        decisions = (*session.decisions, decision) if decision is not None else session.decisions
        known_information = (
            evidence_result.known_information if evidence_result is not None else session.known_information
        )
        unresolved = (
            tuple(evidence_result.unresolved_information)
            if evidence_result is not None
            else session.unresolved_information
        )
        interaction_count = session.interaction_count + 1
        answers = session.answers if is_initial else (*session.answers, message)
        memory_snapshot = session.memory_snapshot
        if workflow_result.success:
            memory = DiagnosticMemoryEngine(self.memory_policy, session.memory_snapshot)
            facts = self._memory_facts(
                session,
                message,
                known_information,
                is_initial=is_initial,
                created_at=now,
            )
            entry = MemoryEntry(
                facts=facts,
                hypotheses=hypotheses,
                evidences=(evidence_result.evidence,) if evidence_result is not None else (),
                questions=(current_question,) if current_question else (),
                answers=(message,) if not is_initial and message.strip() else (),
            )
            memory_snapshot = memory.add_entry(entry, known_information=known_information)
            known_information = memory_snapshot.known_information

        planner_result = self._build_plan(
            workflow_result,
            memory_snapshot=memory_snapshot,
            previous_plan=None if is_initial else session.diagnostic_plan,
            context=context,
        )
        diagnostic_plan = planner_result.plan
        if planner_result.errors:
            metadata["planner_errors"] = tuple(planner_result.errors)
        else:
            metadata.pop("planner_errors", None)

        updated = replace(
            session,
            status=status,
            last_message=message,
            intent=workflow_result.intent if is_initial else session.intent or workflow_result.intent,
            incident=workflow_result.incident if is_initial else session.incident or workflow_result.incident,
            knowledge_result=tuple(workflow_result.knowledge_result or session.knowledge_result),
            hypotheses=hypotheses,
            evidence_history=evidence_history,
            decisions=decisions,
            questions_asked=questions_asked or session.questions_asked,
            answers=answers,
            known_information=known_information,
            memory_snapshot=memory_snapshot,
            diagnostic_plan=diagnostic_plan,
            planner_result=planner_result,
            unresolved_information=unresolved,
            current_question=current_question,
            user_confirmation=user_confirmation,
            updated_at_monotonic=now,
            interaction_count=interaction_count,
            metadata=metadata,
            errors=(*session.errors, *errors),
        )
        response = self._response_message(decision, status)
        return self._turn(updated, workflow_result, response, previous_status, True)

    def _status_for(self, result: WorkflowResult) -> DiagnosticSessionStatus:
        if not result.success or result.decision is None:
            return DiagnosticSessionStatus.FAILED
        mapping = {
            DecisionType.ASK_QUESTION: DiagnosticSessionStatus.WAITING_USER,
            DecisionType.RUN_TEST: DiagnosticSessionStatus.READY_FOR_TEST,
            DecisionType.REQUEST_CONFIRMATION: DiagnosticSessionStatus.WAITING_CONFIRMATION,
            DecisionType.RECOMMEND_ACTION: DiagnosticSessionStatus.READY_FOR_ACTION,
        }
        decision_type = result.decision.decision_type
        if decision_type == DecisionType.ESCALATE_TO_HUMAN:
            return (
                DiagnosticSessionStatus.ESCALATED
                if self.policy.auto_escalate_on_human_decision
                else DiagnosticSessionStatus.ACTIVE
            )
        if decision_type == DecisionType.COMPLETE:
            return (
                DiagnosticSessionStatus.COMPLETED
                if self.policy.auto_complete_on_decision_complete
                else DiagnosticSessionStatus.ACTIVE
            )
        if decision_type == DecisionType.INSUFFICIENT_INFORMATION:
            if result.decision.next_question:
                return DiagnosticSessionStatus.WAITING_USER
            return (
                DiagnosticSessionStatus.ESCALATED
                if self.policy.auto_escalate_on_human_decision
                else DiagnosticSessionStatus.FAILED
            )
        return mapping.get(decision_type, DiagnosticSessionStatus.ACTIVE)

    @staticmethod
    def _response_message(decision: Decision | None, status: DiagnosticSessionStatus) -> str:
        if decision is None:
            return "Não foi possível processar o diagnóstico."
        if decision.decision_type == DecisionType.INSUFFICIENT_INFORMATION:
            return "Ainda não há informações suficientes para concluir o diagnóstico."
        if status == DiagnosticSessionStatus.ESCALATED:
            return "Este caso precisa de atendimento técnico humano."
        if decision.decision_type == DecisionType.ASK_QUESTION:
            return decision.next_question or decision.message
        if decision.decision_type == DecisionType.RUN_TEST:
            return f"Realize o teste recomendado: {decision.recommended_test or decision.message}"
        if decision.decision_type == DecisionType.REQUEST_CONFIRMATION:
            return decision.message or f"Confirma a recomendação: {decision.recommended_action}?"
        if decision.decision_type == DecisionType.RECOMMEND_ACTION:
            return f"Ação recomendada: {decision.recommended_action or decision.message}"
        if decision.decision_type == DecisionType.COMPLETE:
            return f"Diagnóstico concluído: {decision.completion_reason or 'concluído'}"
        return decision.message

    def _blocked_terminal_result(self, session: DiagnosticSession) -> SessionTurnResult | None:
        messages = {
            DiagnosticSessionStatus.CANCELLED: ("A sessão está cancelada.", "cancelled session cannot continue"),
            DiagnosticSessionStatus.FAILED: ("A sessão falhou e não pode continuar.", "failed session cannot continue"),
            DiagnosticSessionStatus.ESCALATED: ("A sessão já foi encaminhada para atendimento humano.", "escalated session cannot continue"),
        }
        if session.status in messages:
            response, error = messages[session.status]
            return self._unchanged_result(session, response, error)
        if session.status == DiagnosticSessionStatus.COMPLETED and not self.policy.allow_restart_after_completion:
            return self._unchanged_result(session, "A sessão já foi concluída.", "completed session cannot continue")
        return None

    def _manual_escalation(self, session: DiagnosticSession, message: str, reason: str) -> SessionTurnResult:
        now = time.monotonic()
        updated = replace(
            session,
            status=DiagnosticSessionStatus.ESCALATED,
            last_message=message,
            current_question=None,
            updated_at_monotonic=now,
            interaction_count=session.interaction_count + 1,
            metadata={**session.metadata, "terminal_reason": reason},
        )
        return self._turn(
            updated,
            None,
            "Este caso precisa de atendimento técnico humano.",
            session.status,
            True,
        )

    def _status_result(self, session: DiagnosticSession) -> SessionTurnResult:
        return self._turn(
            session,
            None,
            f"Status atual da sessão: {session.status.value}.",
            session.status,
            False,
        )

    def _unchanged_result(self, session: DiagnosticSession, response: str, error: str) -> SessionTurnResult:
        return self._turn(session, None, response, session.status, False, errors=(error,))

    @staticmethod
    def _turn(
        session: DiagnosticSession,
        workflow_result: WorkflowResult | None,
        response: str,
        previous_status: DiagnosticSessionStatus,
        state_changed: bool,
        errors: tuple[str, ...] = (),
    ) -> SessionTurnResult:
        return SessionTurnResult(
            session=session,
            workflow_result=workflow_result,
            response_message=response,
            next_expected_input=session.current_question,
            state_changed=state_changed,
            previous_status=previous_status,
            current_status=session.status,
            errors=errors or session.errors[-1:],
        )

    def _is_repeated_answer(self, session: DiagnosticSession, message: str) -> bool:
        if self.policy.max_repeated_answers == 0:
            return False
        normalized = normalize_text(message)
        repeats = sum(normalize_text(answer) == normalized for answer in session.answers)
        return repeats >= self.policy.max_repeated_answers

    @staticmethod
    def _dedupe_evidence(items):
        deduped = []
        identifiers = set()
        for item in items:
            identifier = item.evidence_id
            if identifier not in identifiers:
                identifiers.add(identifier)
                deduped.append(item)
        return tuple(deduped)

    def _build_plan(
        self,
        workflow_result: WorkflowResult,
        *,
        memory_snapshot: MemorySnapshot,
        previous_plan,
        context: DiagnosticContext | None,
    ) -> DiagnosticPlanResult:
        try:
            return self.planner_engine.build_plan(
                hypotheses=workflow_result.hypotheses,
                decision=workflow_result.decision,
                evidence_result=workflow_result.evidence_result,
                knowledge_result=workflow_result.knowledge_result,
                memory_snapshot=memory_snapshot,
                previous_plan=previous_plan,
                context=context,
            )
        except Exception as exc:  # Planner failures must not invalidate a successful workflow.
            return DiagnosticPlanResult(
                success=False,
                errors=(f"Planner: {type(exc).__name__}: {exc}",),
                reasoning=("O planejamento falhou sem alterar o resultado do diagnóstico.",),
            )

    @staticmethod
    def _memory_facts(
        session: DiagnosticSession,
        message: str,
        known_information: dict[str, object],
        *,
        is_initial: bool,
        created_at: float,
    ) -> tuple[MemoryFact, ...]:
        facts = []
        if is_initial:
            facts.append(
                MemoryFact(
                    id=f"{session.session_id}:original_message",
                    category="session",
                    key="original_message",
                    value=message,
                    confidence=1.0,
                    created_at=created_at,
                    source="user",
                )
            )
        else:
            facts.append(
                MemoryFact(
                    id=f"{session.session_id}:answer:{session.interaction_count}",
                    category="conversation",
                    key="last_answer",
                    value=message,
                    confidence=1.0,
                    created_at=created_at,
                    source="user",
                )
            )
        for key, value in known_information.items():
            facts.append(
                MemoryFact(
                    id=f"{session.session_id}:diagnostic:{key}",
                    category="diagnostic",
                    key=str(key),
                    value=value,
                    confidence=1.0,
                    created_at=created_at,
                    source="workflow",
                )
            )
        return tuple(facts)

    @staticmethod
    def _validate_message(message: str) -> None:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must not be empty")
