import time
from dataclasses import replace
from uuid import uuid4

from app.services.diagnostic_engine.approval_engine import DiagnosticApprovalEngine
from app.services.diagnostic_engine.approval_models import (
    ActionApprovalRequest,
    ApprovalActor,
    ApprovalDecision,
    ApprovalResult,
    ApprovalStatus,
    ApprovedActionGrant,
)
from app.services.diagnostic_engine.decision_models import Decision, DecisionType
from app.services.diagnostic_engine.execution_engine import DiagnosticExecutionEngine
from app.services.diagnostic_engine.execution_models import ExecutionResult, ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.executor_engine import DiagnosticExecutorEngine
from app.services.diagnostic_engine.executor_models import ExecutorRequest, ExecutorResult
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType,
    LocalExecutionContract,
    LocalExecutionState,
    LocalOperationArgument,
    LocalOperationType,
    LocalRawExecutionResult,
    LocalSanitizedResult,
)
from app.services.diagnostic_engine.local_operation_validator import (
    LocalOperationValidationResult,
    SafeLocalOperationValidator,
)
from app.services.diagnostic_engine.local_system_information_adapter import LocalSystemInformationAdapter
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
        execution_engine: DiagnosticExecutionEngine | None = None,
        approval_engine: DiagnosticApprovalEngine | None = None,
        executor_engine: DiagnosticExecutorEngine | None = None,
        local_operation_validator: SafeLocalOperationValidator | None = None,
        local_system_information_adapter: LocalSystemInformationAdapter | None = None,
    ) -> None:
        self.workflow_engine = workflow_engine if workflow_engine is not None else DiagnosticWorkflowEngine()
        self.policy = policy if policy is not None else DiagnosticSessionPolicy()
        self.memory_policy = memory_policy if memory_policy is not None else DiagnosticMemoryPolicy()
        self.planner_engine = planner_engine if planner_engine is not None else DiagnosticPlannerEngine()
        self.execution_engine = execution_engine if execution_engine is not None else DiagnosticExecutionEngine()
        self.approval_engine = approval_engine if approval_engine is not None else DiagnosticApprovalEngine()
        self.executor_engine = executor_engine if executor_engine is not None else DiagnosticExecutorEngine()
        self.local_operation_validator = (
            local_operation_validator if local_operation_validator is not None else SafeLocalOperationValidator()
        )
        self.local_system_information_adapter = (
            local_system_information_adapter
            if local_system_information_adapter is not None
            else LocalSystemInformationAdapter()
        )

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

        execution_result = self._build_execution(
            diagnostic_plan,
            previous_execution_plan=None if is_initial else session.execution_plan,
        )
        execution_plan = execution_result.execution_plan
        if execution_result.errors:
            metadata["execution_errors"] = tuple(dict.fromkeys(execution_result.errors))
        else:
            metadata.pop("execution_errors", None)

        approval_requests, approval_result = self._build_approvals(
            session,
            execution_plan,
            now_monotonic=now,
        )
        metadata = self._metadata_with_approval_errors(metadata, approval_result)

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
            execution_plan=execution_plan,
            execution_result=execution_result,
            approval_requests=approval_requests,
            approval_result=approval_result,
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

    def request_action_approval(
        self,
        session: DiagnosticSession,
        action_id: str,
        requested_by: ApprovalActor | None = None,
        now_monotonic: float = 0.0,
        ttl_seconds: int | None = None,
    ) -> SessionTurnResult:
        action = self._find_action(session, action_id)
        if action is None or session.execution_plan is None:
            return self._approval_failure_turn(session, f"Action {action_id!r} was not found in the execution plan.")
        duplicate = next(
            (
                item for item in session.approval_requests
                if item.status == ApprovalStatus.PENDING
                and item.execution_plan_id == session.execution_plan.plan_id
                and item.action_id == action.action_id
                and item.action_snapshot == action
            ),
            None,
        )
        if duplicate is not None:
            result = ApprovalResult(
                success=True,
                request=duplicate,
                reasoning=("An equivalent approval request is already pending.",),
            )
            return self._approval_turn(session, result, "A solicitação de aprovação já está pendente.", changed=False)
        result = self._call_approval(
            "create_request",
            session.execution_plan,
            action,
            session_id=session.session_id,
            requested_by=requested_by,
            now_monotonic=now_monotonic,
            ttl_seconds=ttl_seconds,
        )
        requests = (*session.approval_requests, result.request) if result.success and result.request else session.approval_requests
        return self._approval_turn(
            session,
            result,
            "Solicitação de aprovação registrada." if result.success else "Não foi possível solicitar aprovação.",
            approval_requests=requests,
            changed=result.success,
        )

    def _build_approvals(
        self,
        session: DiagnosticSession,
        execution_plan,
        *,
        now_monotonic: float,
    ) -> tuple[tuple[ActionApprovalRequest, ...], ApprovalResult | None]:
        requests = session.approval_requests
        current_result = session.approval_result
        if execution_plan is None:
            return requests, current_result
        for action in execution_plan.actions:
            if not self.approval_engine.policy.requires_approval(action.risk):
                continue
            duplicate = any(
                item.status == ApprovalStatus.PENDING
                and item.execution_plan_id == execution_plan.plan_id
                and item.action_id == action.action_id
                and item.action_snapshot == action
                for item in requests
            )
            if duplicate:
                continue
            result = self._call_approval(
                "create_request",
                execution_plan,
                action,
                session_id=session.session_id,
                now_monotonic=now_monotonic,
            )
            current_result = result
            if result.success and result.request is not None:
                requests = (*requests, result.request)
        return requests, current_result

    def _call_approval(self, method_name: str, *args, **kwargs) -> ApprovalResult:
        try:
            method = getattr(self.approval_engine, method_name)
            result = method(*args, **kwargs)
            if not isinstance(result, ApprovalResult):
                raise TypeError(f"{method_name} must return ApprovalResult")
            return result
        except Exception as exc:  # Approval failures must preserve the diagnostic session.
            return ApprovalResult(
                success=False,
                errors=(f"Approval: {type(exc).__name__}: {exc}",),
            )

    def _approval_failure_turn(self, session: DiagnosticSession, error: str) -> SessionTurnResult:
        return self._approval_turn(
            session,
            ApprovalResult(success=False, errors=(error,)),
            "Não foi possível atualizar a aprovação.",
            changed=False,
        )

    def _approval_turn(
        self,
        session: DiagnosticSession,
        result: ApprovalResult,
        response: str,
        *,
        approval_requests: tuple[ActionApprovalRequest, ...] | None = None,
        approval_decisions: tuple[ApprovalDecision, ...] | None = None,
        approval_grants: tuple[ApprovedActionGrant, ...] | None = None,
        changed: bool,
    ) -> SessionTurnResult:
        metadata = self._metadata_with_approval_errors(dict(session.metadata), result)
        updated = replace(
            session,
            approval_requests=session.approval_requests if approval_requests is None else approval_requests,
            approval_decisions=session.approval_decisions if approval_decisions is None else approval_decisions,
            approval_grants=session.approval_grants if approval_grants is None else approval_grants,
            approval_result=result,
            metadata=metadata,
        )
        return self._turn(updated, None, response, session.status, changed, errors=result.errors)

    @staticmethod
    def _metadata_with_approval_errors(
        metadata: dict[str, object],
        result: ApprovalResult | None,
    ) -> dict[str, object]:
        if result is None or not result.errors:
            return metadata
        existing = tuple(metadata.get("approval_errors", ()))
        metadata["approval_errors"] = tuple(dict.fromkeys((*existing, *result.errors)))
        return metadata

    @staticmethod
    def _find_action(session: DiagnosticSession, action_id: str | None):
        if session.execution_plan is None or not isinstance(action_id, str):
            return None
        return next((item for item in session.execution_plan.actions if item.action_id == action_id), None)

    @staticmethod
    def _find_request(session: DiagnosticSession, approval_id: str):
        return next(
            (item for item in reversed(session.approval_requests) if item.approval_id == approval_id),
            None,
        )

    def decide_action_approval(
        self,
        session: DiagnosticSession,
        approval_id: str,
        status: ApprovalStatus,
        decided_by: ApprovalActor,
        now_monotonic: float,
        reason: str | None = None,
    ) -> SessionTurnResult:
        request = self._find_request(session, approval_id)
        if request is None:
            return self._approval_failure_turn(session, f"Approval request {approval_id!r} was not found.")
        result = self._call_approval(
            "decide", request, status, decided_by, now_monotonic, reason=reason
        )
        decisions = (*session.approval_decisions, result.decision) if result.success and result.decision else session.approval_decisions
        return self._approval_turn(
            session,
            result,
            "Decisão de aprovação registrada." if result.success else "Não foi possível registrar a decisão.",
            approval_decisions=decisions,
            changed=result.success,
        )

    def create_action_grant(
        self,
        session: DiagnosticSession,
        approval_id: str,
        now_monotonic: float,
    ) -> SessionTurnResult:
        request = self._find_request(session, approval_id)
        decision = next(
            (
                item for item in reversed(session.approval_decisions)
                if item.approval_id == approval_id and item.status == ApprovalStatus.APPROVED
            ),
            None,
        )
        action = self._find_action(session, request.action_id if request else None)
        if request is None:
            return self._approval_failure_turn(session, f"Approval request {approval_id!r} was not found.")
        if decision is None:
            return self._approval_failure_turn(session, "An APPROVED decision was not found for the request.")
        if action is None:
            return self._approval_failure_turn(session, "The approved action was not found in the execution plan.")
        result = self._call_approval("create_grant", request, decision, action, now_monotonic)
        grants = (*session.approval_grants, result.grant) if result.success and result.grant else session.approval_grants
        return self._approval_turn(
            session,
            result,
            "Grant de aprovação registrado." if result.success else "Não foi possível criar o grant.",
            approval_grants=grants,
            changed=result.success,
        )

    def consume_action_grant(
        self,
        session: DiagnosticSession,
        grant_id: str,
        action_id: str,
        now_monotonic: float,
    ) -> SessionTurnResult:
        grant = next((item for item in reversed(session.approval_grants) if item.grant_id == grant_id), None)
        action = self._find_action(session, action_id)
        if grant is None:
            return self._approval_failure_turn(session, f"Approval grant {grant_id!r} was not found.")
        if action is None:
            return self._approval_failure_turn(session, f"Action {action_id!r} was not found in the execution plan.")
        result = self._call_approval("consume_grant", grant, action, now_monotonic)
        grants = (*session.approval_grants, result.grant) if result.success and result.grant else session.approval_grants
        return self._approval_turn(
            session,
            result,
            "Grant marcado como utilizado; nenhuma ação foi executada." if result.success else "Não foi possível consumir o grant.",
            approval_grants=grants,
            changed=result.success,
        )

    def build_executor_request(
        self,
        session: DiagnosticSession,
        action_id: str,
        grant_id: str,
        now_monotonic: float,
        dry_run: bool = True,
        timeout_seconds: int | None = None,
    ) -> SessionTurnResult:
        """Build and record an executor contract without executing its action."""
        action = self._find_action(session, action_id)
        grant = next(
            (item for item in reversed(session.approval_grants) if item.grant_id == grant_id),
            None,
        )
        if session.execution_plan is None:
            return self._executor_failure_turn(session, "The session has no execution plan.")
        if action is None:
            return self._executor_failure_turn(
                session, f"Action {action_id!r} was not found in the execution plan."
            )
        if grant is None:
            return self._executor_failure_turn(
                session, f"Approval grant {grant_id!r} was not found in the session history."
            )
        if grant.execution_plan_id != session.execution_plan.plan_id:
            return self._executor_failure_turn(
                session, "The approval grant does not belong to the current execution plan."
            )

        expected_timeout = (
            self.executor_engine.policy.default_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        duplicate = next(
            (
                item for item in reversed(session.executor_requests)
                if item.context.execution_plan_id == session.execution_plan.plan_id
                and item.context.action_id == action.action_id
                and item.context.grant_id == grant.grant_id
                and item.dry_run == dry_run
                and item.timeout_seconds == expected_timeout
                and not item.grant_snapshot.used
            ),
            None,
        )
        if duplicate is not None:
            existing = next(
                (
                    item for item in reversed(session.executor_results)
                    if item.request == duplicate
                ),
                None,
            )
            result = existing or ExecutorResult(
                success=False,
                request=duplicate,
                reasoning=("An equivalent executor request already exists.",),
            )
            return self._executor_turn(
                session,
                result,
                "A requisição equivalente do executor já está registrada.",
                changed=False,
                record=False,
            )

        result = self._call_executor(
            "build_request",
            session_id=session.session_id,
            diagnostic_plan_id=session.diagnostic_plan.plan_id if session.diagnostic_plan else None,
            execution_plan=session.execution_plan,
            action=action,
            grant=grant,
            now_monotonic=now_monotonic,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
        )
        return self._executor_turn(
            session,
            result,
            "Requisição estrutural do executor registrada." if result.request else "Não foi possível criar a requisição do executor.",
            changed=True,
        )

    def validate_executor_request(
        self,
        session: DiagnosticSession,
        request_id: str,
        now_monotonic: float,
    ) -> SessionTurnResult:
        """Validate a recorded executor request without executing its action."""
        request = self._find_executor_request(session, request_id)
        if request is None:
            return self._executor_failure_turn(
                session, f"Executor request {request_id!r} was not found."
            )
        result = self._call_executor("validate_request", request, now_monotonic)
        return self._executor_turn(
            session,
            result,
            "Requisição do executor validada estruturalmente." if result.attempt else "A validação estrutural foi bloqueada.",
            changed=True,
        )

    def simulate_executor_request(
        self,
        session: DiagnosticSession,
        request_id: str,
        now_monotonic: float,
    ) -> SessionTurnResult:
        """Record a structural dry-run; this method never executes the action."""
        request = self._find_executor_request(session, request_id)
        if request is None:
            return self._executor_failure_turn(
                session, f"Executor request {request_id!r} was not found."
            )
        result = self._call_executor("simulate", request, now_monotonic)
        return self._executor_turn(
            session,
            result,
            "Dry-run estrutural concluído; nenhuma ação foi executada."
            if result.success
            else "O dry-run estrutural foi bloqueado; nenhuma ação foi executada.",
            changed=True,
        )

    def _call_executor(self, method_name: str, *args, **kwargs) -> ExecutorResult:
        try:
            method = getattr(self.executor_engine, method_name)
            result = method(*args, **kwargs)
            if not isinstance(result, ExecutorResult):
                raise TypeError(f"{method_name} must return ExecutorResult")
            return result
        except Exception as exc:  # Executor failures must preserve the diagnostic session.
            return ExecutorResult(
                success=False,
                errors=(f"Executor: {type(exc).__name__}: {exc}",),
                reasoning=("The executor boundary blocked the operation without executing an action.",),
            )

    def _executor_failure_turn(self, session: DiagnosticSession, error: str) -> SessionTurnResult:
        return self._executor_turn(
            session,
            ExecutorResult(success=False, errors=(error,)),
            "Não foi possível atualizar o executor.",
            changed=True,
        )

    def _executor_turn(
        self,
        session: DiagnosticSession,
        result: ExecutorResult,
        response: str,
        *,
        changed: bool,
        record: bool = True,
    ) -> SessionTurnResult:
        if not record:
            return self._turn(session, None, response, session.status, changed, errors=result.errors)

        requests = session.executor_requests
        if result.request is not None and result.request not in requests:
            requests = (*requests, result.request)
        attempts = (
            (*session.execution_attempts, result.attempt)
            if result.attempt is not None
            else session.execution_attempts
        )
        trails = session.execution_audit_trails
        if result.request is not None and result.audit_events:
            try:
                trail = self.executor_engine.build_audit_trail(
                    session.session_id,
                    result.request.context.execution_plan_id,
                    result.audit_events,
                    (result.attempt,) if result.attempt is not None else (),
                )
                trails = (*trails, trail)
            except Exception as exc:
                result = ExecutorResult(
                    success=False,
                    request=result.request,
                    attempt=result.attempt,
                    audit_events=result.audit_events,
                    reasoning=result.reasoning,
                    errors=(*result.errors, f"Executor audit: {type(exc).__name__}: {exc}"),
                    metadata=result.metadata,
                )
        metadata = dict(session.metadata)
        if result.errors:
            existing = tuple(metadata.get("executor_errors", ()))
            metadata["executor_errors"] = tuple(dict.fromkeys((*existing, *result.errors)))
        updated = replace(
            session,
            executor_requests=requests,
            execution_attempts=attempts,
            executor_results=(*session.executor_results, result),
            execution_audit_trails=trails,
            current_executor_result=result,
            metadata=metadata,
        )
        return self._turn(updated, None, response, session.status, changed, errors=result.errors)

    @staticmethod
    def _find_executor_request(session: DiagnosticSession, request_id: str) -> ExecutorRequest | None:
        if not isinstance(request_id, str):
            return None
        return next(
            (item for item in reversed(session.executor_requests) if item.request_id == request_id),
            None,
        )

    def build_local_execution_contract(
        self,
        session: DiagnosticSession,
        *,
        request_id: str,
        operation_name: str,
        command_id: str,
        contract_id: str,
        now_monotonic: float,
        arguments: tuple[LocalOperationArgument, ...] = (),
        timeout_seconds: int | None = None,
        dry_run: bool = True,
    ) -> SessionTurnResult:
        """Build a local structural contract; this method never executes it."""
        if operation_name != "read_system_information":
            return self._local_failure_turn(
                session, "Only read_system_information is supported by the local integration."
            )
        request = self._find_executor_request(session, request_id)
        if request is None:
            return self._local_failure_turn(session, f"Executor request {request_id!r} was not found.")
        action = self._find_action(session, request.context.action_id)
        if action is None:
            return self._local_failure_turn(session, "The approved execution action was not found.")
        grant = next(
            (
                item for item in reversed(session.approval_grants)
                if item.grant_id == request.context.grant_id
            ),
            None,
        )
        if grant is None:
            return self._local_failure_turn(session, "The approved action grant was not found.")

        expected_timeout = 30 if timeout_seconds is None else timeout_seconds
        duplicate = next(
            (
                item for item in reversed(session.local_execution_contracts)
                if item.executor_request_id == request_id
                and item.operation.operation_name == operation_name
                and item.command.command_id == command_id
                and item.command.arguments == arguments
                and item.command.timeout_seconds == expected_timeout
                and item.command.dry_run == dry_run
            ),
            None,
        )
        if duplicate is not None:
            return self._turn(
                session,
                None,
                "Contrato local equivalente já registrado; nenhuma operação foi executada.",
                session.status,
                False,
            )
        try:
            result = self.local_operation_validator.build_contract(
                executor_request=request,
                execution_action=action,
                grant=grant,
                operation_name=operation_name,
                arguments=arguments,
                command_id=command_id,
                contract_id=contract_id,
                created_at_monotonic=now_monotonic,
                timeout_seconds=timeout_seconds,
                dry_run=dry_run,
            )
            if not isinstance(result, LocalOperationValidationResult):
                raise TypeError("build_contract must return LocalOperationValidationResult")
        except Exception:
            result = LocalOperationValidationResult(
                success=False,
                errors=("Falha controlada ao validar o contrato local.",),
            )
        if not result.success or result.contract is None:
            return self._local_failure_turn(
                session,
                *(result.errors or ("The local operation validator blocked the contract.",)),
            )
        updated = replace(
            session,
            local_execution_contracts=(*session.local_execution_contracts, result.contract),
            current_local_execution_contract=result.contract,
        )
        return self._turn(
            updated,
            None,
            "Contrato local read_system_information registrado; nenhuma coleta foi executada.",
            session.status,
            True,
        )

    def execute_local_contract(
        self,
        session: DiagnosticSession,
        *,
        contract_id: str,
        now_monotonic: float,
    ) -> SessionTurnResult:
        """Explicitly run the sole read-only local adapter and store sanitized output."""
        contract = next(
            (
                item for item in reversed(session.local_execution_contracts)
                if item.contract_id == contract_id
            ),
            None,
        )
        if contract is None:
            return self._local_failure_turn(session, f"Local contract {contract_id!r} was not found.")
        try:
            error = self._local_execution_error(session, contract, now_monotonic)
        except Exception:
            error = "Falha controlada ao revalidar o contrato local."
        if error is not None:
            return self._local_failure_turn(session, error)
        try:
            raw = self.local_system_information_adapter.execute(contract, now_monotonic)
            if not isinstance(raw, LocalRawExecutionResult):
                raise TypeError("execute must return LocalRawExecutionResult")
        except Exception:
            raw = self._local_raw_failure(
                contract.command.command_id,
                now_monotonic,
                "Falha controlada ao executar read_system_information.",
            )
        try:
            sanitized = self.local_system_information_adapter.sanitize(raw)
            if not isinstance(sanitized, LocalSanitizedResult):
                raise TypeError("sanitize must return LocalSanitizedResult")
        except Exception:
            sanitized = LocalSanitizedResult(
                command_id=raw.command_id,
                state=LocalExecutionState.FAILED,
                exit_code=None,
                stdout_summary="",
                stderr_summary="Falha controlada ao sanitizar o resultado local.",
                redactions=(),
                truncated=False,
                output_bytes=0,
                errors=("Falha controlada ao sanitizar o resultado local.",),
            )
        errors = tuple(dict.fromkeys((*raw.errors, *sanitized.errors)))
        metadata = self._metadata_with_local_errors(dict(session.metadata), errors)
        updated = replace(
            session,
            local_raw_results=(*session.local_raw_results, raw),
            local_sanitized_results=(*session.local_sanitized_results, sanitized),
            current_local_execution_contract=contract,
            current_local_raw_result=raw,
            current_local_sanitized_result=sanitized,
            metadata=metadata,
        )
        response = (
            "Dry-run local concluído; nenhuma coleta real foi realizada."
            if contract.command.dry_run and raw.state == LocalExecutionState.SUCCESS
            else "Coleta local read_system_information concluída com saída sanitizada."
            if raw.state == LocalExecutionState.SUCCESS
            else "A coleta local falhou de forma controlada."
        )
        return self._turn(updated, None, response, session.status, True, errors=errors)

    def _local_execution_error(
        self,
        session: DiagnosticSession,
        contract: LocalExecutionContract,
        now_monotonic: float,
    ) -> str | None:
        operation = contract.operation
        command = contract.command
        if (
            not isinstance(now_monotonic, int | float)
            or isinstance(now_monotonic, bool)
            or now_monotonic < 0
        ):
            return "The local execution timestamp is invalid."
        if operation.operation_name != "read_system_information" or command.operation_name != "read_system_information":
            return "Only read_system_information can be executed locally."
        if operation.adapter_type != LocalAdapterType.SYSTEM_INFORMATION or command.adapter_type != LocalAdapterType.SYSTEM_INFORMATION:
            return "The local contract adapter is invalid."
        if operation.operation_type != LocalOperationType.READ_ONLY or command.operation_type != LocalOperationType.READ_ONLY:
            return "The local contract operation type is invalid."
        if command.target != ExecutionTarget.WINDOWS or command.risk != ExecutionRisk.LOW:
            return "The local contract target or risk is invalid."
        if command.arguments:
            return "read_system_information does not accept arguments."
        sandbox = contract.sandbox_policy
        if any(
            (
                sandbox.allow_shell,
                sandbox.allow_arbitrary_command,
                sandbox.allow_environment_inheritance,
                sandbox.allow_network_access,
                sandbox.allow_filesystem_write,
                sandbox.allow_registry_write,
                sandbox.allow_service_state_change,
                sandbox.allow_process_termination,
                sandbox.allow_elevation,
                sandbox.allow_child_processes,
            )
        ):
            return "The local contract sandbox is not conservative."
        request = self._find_executor_request(session, contract.executor_request_id)
        if request is None or request.context.action_id != contract.action_id or request.context.grant_id != contract.grant_id:
            return "The local contract no longer matches its ExecutorRequest."
        action = self._find_action(session, contract.action_id)
        grant = next(
            (item for item in reversed(session.approval_grants) if item.grant_id == contract.grant_id),
            None,
        )
        if action is None or grant is None:
            return "The local contract action or grant is missing."
        if request.action_snapshot != action or request.grant_snapshot != grant or grant.action_snapshot != action:
            return "The local contract snapshots no longer match."
        if grant.used:
            return "The local contract grant was already used."
        if grant.expires_at_monotonic is not None and now_monotonic >= grant.expires_at_monotonic:
            return "The local contract grant expired."
        if not command.dry_run and not self.local_operation_validator.policy.can_execute_real_operation(
            adapter_type=operation.adapter_type,
            target=command.target,
            risk=command.risk,
            operation_type=command.operation_type,
        ):
            return "The local policy blocks real execution."
        return None

    def _local_failure_turn(self, session: DiagnosticSession, *errors: str) -> SessionTurnResult:
        unique = tuple(dict.fromkeys(error for error in errors if error))
        metadata = self._metadata_with_local_errors(dict(session.metadata), unique)
        updated = replace(session, metadata=metadata)
        return self._turn(
            updated,
            None,
            "A operação local foi bloqueada de forma controlada.",
            session.status,
            True,
            errors=unique,
        )

    @staticmethod
    def _metadata_with_local_errors(
        metadata: dict[str, object], errors: tuple[str, ...]
    ) -> dict[str, object]:
        if errors:
            existing = tuple(metadata.get("local_execution_errors", ()))
            metadata["local_execution_errors"] = tuple(dict.fromkeys((*existing, *errors)))
        return metadata

    @staticmethod
    def _local_raw_failure(
        command_id: str, now_monotonic: float, message: str
    ) -> LocalRawExecutionResult:
        timestamp = (
            now_monotonic
            if isinstance(now_monotonic, int | float)
            and not isinstance(now_monotonic, bool)
            and now_monotonic >= 0
            else None
        )
        return LocalRawExecutionResult(
            command_id=command_id,
            state=LocalExecutionState.FAILED,
            started_at_monotonic=timestamp,
            finished_at_monotonic=timestamp,
            exit_code=None,
            stdout="",
            stderr=message,
            output_chunks=(),
            timed_out=False,
            cancelled=False,
            errors=(message,),
        )

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

    def _build_execution(
        self,
        diagnostic_plan,
        *,
        previous_execution_plan,
    ) -> ExecutionResult:
        try:
            return self.execution_engine.build_execution_plan(
                diagnostic_plan=diagnostic_plan,
                previous_execution_plan=previous_execution_plan,
            )
        except Exception as exc:  # Execution planning must not invalidate the diagnostic session.
            return ExecutionResult(
                success=False,
                errors=(f"Execution: {type(exc).__name__}: {exc}",),
                reasoning=("A descrição de execução falhou sem alterar o diagnóstico.",),
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
