"""Deterministic validation and structural dry-run for executor contracts."""

from copy import deepcopy

from app.services.diagnostic_engine.approval_models import ApprovedActionGrant
from app.services.diagnostic_engine.execution_models import ExecutionAction, ExecutionPlan
from app.services.diagnostic_engine.executor_models import (
    AuditEvent,
    AuditEventType,
    ExecutionAttempt,
    ExecutionAuditTrail,
    ExecutionContext,
    ExecutorBlockReason,
    ExecutorRequest,
    ExecutorResult,
    ExecutorStatus,
    RollbackPlan,
)
from app.services.diagnostic_engine.executor_policy import DiagnosticExecutorPolicy


class DiagnosticExecutorEngine:
    """Validate authorization and simulate structure without executing actions."""

    def __init__(self, policy: DiagnosticExecutorPolicy | None = None) -> None:
        self.policy = policy if policy is not None else DiagnosticExecutorPolicy()

    def build_request(
        self,
        session_id: str,
        diagnostic_plan_id: str | None,
        execution_plan: ExecutionPlan,
        action: ExecutionAction,
        grant: ApprovedActionGrant,
        now_monotonic: float,
        dry_run: bool = True,
        timeout_seconds: int | None = None,
    ) -> ExecutorResult:
        request_id = self._request_id(execution_plan, action, grant)
        if not isinstance(session_id, str) or not session_id.strip():
            return self._early_failure("session_id must not be empty")
        if not isinstance(execution_plan, ExecutionPlan):
            return self._early_failure("execution_plan must be an ExecutionPlan")
        if not isinstance(action, ExecutionAction):
            return self._early_failure("action must be an ExecutionAction")
        if not isinstance(grant, ApprovedActionGrant):
            return self._early_failure("grant is required", ExecutorBlockReason.MISSING_GRANT, request_id)
        if not self._valid_time(now_monotonic):
            return self._early_failure("now_monotonic must be a non-negative number")
        if not isinstance(dry_run, bool):
            return self._early_failure("dry_run must be a boolean", ExecutorBlockReason.INVALID_PARAMETERS, request_id)
        plan_action = next((item for item in execution_plan.actions if item.action_id == action.action_id), None)
        if plan_action is None or plan_action != action:
            return self._early_failure("The action does not belong to the execution plan.", ExecutorBlockReason.ACTION_MISMATCH, request_id)
        if grant.action_id != action.action_id:
            return self._early_failure("The grant action_id does not match the action.", ExecutorBlockReason.ACTION_MISMATCH, request_id)
        if grant.execution_plan_id != execution_plan.plan_id:
            return self._early_failure("The grant execution_plan_id does not match the plan.", ExecutorBlockReason.PLAN_MISMATCH, request_id)
        if self.policy.require_action_snapshot_match and grant.action_snapshot != action:
            return self._early_failure("The grant action snapshot does not match.", ExecutorBlockReason.ACTION_MISMATCH, request_id)
        if self.policy.require_unexpired_grant and self._expired(grant, now_monotonic):
            return self._early_failure("The grant expired.", ExecutorBlockReason.EXPIRED_GRANT, request_id)
        if self.policy.reject_used_grants and grant.used:
            return self._early_failure("The grant was already used.", ExecutorBlockReason.USED_GRANT, request_id)
        if not self.policy.is_target_allowed(action.target):
            return self._early_failure(f"Target {action.target.value} is blocked.", ExecutorBlockReason.TARGET_BLOCKED, request_id)
        if not self.policy.is_risk_allowed(action.risk):
            return self._early_failure(f"Risk {action.risk.value} is blocked.", ExecutorBlockReason.RISK_BLOCKED, request_id)
        action_type = action.metadata.get("action_kind")
        if not isinstance(action_type, str):
            return self._early_failure("The action type is not explicitly classified.", ExecutorBlockReason.POLICY_BLOCKED, request_id)
        if not self.policy.is_action_type_allowed(action_type):
            reason = ExecutorBlockReason.DESTRUCTIVE_ACTION if action_type == "destructive" else ExecutorBlockReason.POLICY_BLOCKED
            return self._early_failure(f"Action type {action_type} is blocked.", reason, request_id)
        if self.policy.requires_dry_run(action.risk) and not dry_run:
            return self._early_failure(f"Risk {action.risk.value} requires dry-run.", ExecutorBlockReason.POLICY_BLOCKED, request_id)
        timeout = self.policy.default_timeout_seconds if timeout_seconds is None else timeout_seconds
        if not self.policy.validate_timeout(timeout):
            return self._early_failure("timeout_seconds is outside the configured limit.", ExecutorBlockReason.INVALID_PARAMETERS, request_id)
        session_error = self._session_error(session_id, grant)
        if session_error:
            return self._early_failure(session_error, ExecutorBlockReason.SESSION_MISMATCH, request_id)

        try:
            context = ExecutionContext(
                session_id=session_id,
                diagnostic_plan_id=diagnostic_plan_id,
                execution_plan_id=execution_plan.plan_id,
                action_id=action.action_id,
                grant_id=grant.grant_id,
                approval_id=grant.approval_id,
                target=action.target,
                risk=action.risk,
                requested_at_monotonic=now_monotonic,
                metadata=self._metadata(action.metadata),
            )
            request = ExecutorRequest(
                request_id=request_id,
                context=context,
                action_snapshot=action,
                grant_snapshot=grant,
                timeout_seconds=timeout,
                dry_run=dry_run,
                metadata=self._metadata(action.metadata),
            )
        except (TypeError, ValueError) as exc:
            return self._early_failure(str(exc), ExecutorBlockReason.INVALID_PARAMETERS, request_id)
        events = self._events(request, now_monotonic, ((AuditEventType.EXECUTION_REQUESTED, "Executor request created; no action was executed."),))
        attempt = self._attempt(request, ExecutorStatus.PENDING, now_monotonic, events=events)
        return ExecutorResult(
            success=False,
            request=request,
            attempt=attempt,
            audit_events=events,
            reasoning=self._reasoning("The executor request was built without executing the action."),
            metadata=self._metadata(request.metadata),
        )

    def validate_request(self, request: ExecutorRequest, now_monotonic: float) -> ExecutorResult:
        if not isinstance(request, ExecutorRequest):
            return self._early_failure("request must be an ExecutorRequest", ExecutorBlockReason.INVALID_PARAMETERS)
        if not self._valid_time(now_monotonic):
            return self._early_failure("now_monotonic must be a non-negative number", ExecutorBlockReason.INVALID_PARAMETERS, request.request_id)
        initial = [
            (AuditEventType.EXECUTION_REQUESTED, "Execution validation requested."),
            (AuditEventType.VALIDATION_STARTED, "Structural validation started."),
        ]
        error = self._request_error(request, now_monotonic)
        if error is not None:
            reason, message, authorization = error
            event_type = AuditEventType.AUTHORIZATION_REJECTED if authorization else AuditEventType.VALIDATION_FAILED
            events = self._events(request, now_monotonic, (*initial, (event_type, message)))
            return self._blocked(request, reason, message, now_monotonic, events)
        event_specs = (
            *initial,
            (AuditEventType.VALIDATION_PASSED, "Structural validation passed."),
            (AuditEventType.AUTHORIZATION_CHECKED, "Grant authorization checked."),
            (AuditEventType.AUTHORIZATION_ACCEPTED, "Grant authorization accepted."),
        )
        events = self._events(request, now_monotonic, event_specs)
        attempt = self._attempt(request, ExecutorStatus.AUTHORIZED, now_monotonic, events=events)
        return ExecutorResult(
            success=False,
            request=request,
            attempt=attempt,
            rollback_plan=self._rollback_plan(request),
            audit_events=events,
            reasoning=self._reasoning(
                "The grant matches the requested action.",
                f"Target {request.context.target.value} is allowed by policy.",
                "Validation authorized structure only; no action was executed.",
            ),
            metadata=self._metadata(request.metadata),
        )

    def simulate(self, request: ExecutorRequest, now_monotonic: float) -> ExecutorResult:
        validation = self.validate_request(request, now_monotonic)
        if validation.attempt is None or validation.attempt.status != ExecutorStatus.AUTHORIZED:
            return validation
        if not request.dry_run:
            specs = tuple((item.event_type, item.message) for item in validation.audit_events)
            events = self._events(
                request,
                now_monotonic,
                (*specs, (AuditEventType.VALIDATION_FAILED, "simulate requires dry_run=True.")),
            )
            return self._blocked(
                request, ExecutorBlockReason.POLICY_BLOCKED,
                "simulate requires dry_run=True; no action was executed.", now_monotonic, events,
            )
        event_specs = (
            (AuditEventType.EXECUTION_REQUESTED, "Structural dry-run requested."),
            (AuditEventType.VALIDATION_STARTED, "Structural validation started."),
            (AuditEventType.VALIDATION_PASSED, "Structural validation passed."),
            (AuditEventType.AUTHORIZATION_CHECKED, "Grant authorization checked."),
            (AuditEventType.AUTHORIZATION_ACCEPTED, "Grant authorization accepted."),
            (AuditEventType.EXECUTION_STARTED, "Dry-run estrutural iniciado; nenhuma ação foi executada."),
            (AuditEventType.EXECUTION_SUCCEEDED, "Dry-run estrutural concluído; nenhuma alteração foi realizada."),
        )
        events = self._events(request, now_monotonic, event_specs)
        attempt = ExecutionAttempt(
            attempt_id=f"attempt-{request.request_id}-001",
            request_id=request.request_id,
            attempt_number=1,
            status=ExecutorStatus.SUCCESS,
            started_at_monotonic=now_monotonic,
            finished_at_monotonic=now_monotonic,
            exit_code=0,
            output_summary="Dry-run estrutural concluído; nenhuma ação foi executada.",
            error_summary=None,
            block_reason=None,
            audit_events=events,
            metadata=self._metadata(request.metadata),
        )
        return ExecutorResult(
            success=True,
            request=request,
            attempt=attempt,
            rollback_plan=self._rollback_plan(request),
            audit_events=events,
            reasoning=self._reasoning("A simulação estrutural não executa comandos."),
            metadata=self._metadata(request.metadata),
        )

    def build_audit_trail(
        self,
        session_id: str,
        execution_plan_id: str,
        events: tuple[AuditEvent, ...],
        attempts: tuple[ExecutionAttempt, ...],
    ) -> ExecutionAuditTrail:
        return ExecutionAuditTrail(session_id, execution_plan_id, events, attempts)

    def _request_error(
        self, request: ExecutorRequest, now: float
    ) -> tuple[ExecutorBlockReason, str, bool] | None:
        grant = request.grant_snapshot
        action = request.action_snapshot
        context = request.context
        if self.policy.require_valid_grant and not isinstance(grant, ApprovedActionGrant):
            return ExecutorBlockReason.INVALID_GRANT, "The grant snapshot is invalid.", True
        if grant.grant_id != context.grant_id or grant.approval_id != context.approval_id:
            return ExecutorBlockReason.INVALID_GRANT, "Grant identifiers do not match the context.", True
        if grant.action_id != context.action_id or action.action_id != context.action_id:
            return ExecutorBlockReason.ACTION_MISMATCH, "The action does not match the authorization.", True
        if self.policy.require_plan_match and grant.execution_plan_id != context.execution_plan_id:
            return ExecutorBlockReason.PLAN_MISMATCH, "The execution plan does not match the grant.", True
        if self.policy.require_action_snapshot_match and grant.action_snapshot != action:
            return ExecutorBlockReason.ACTION_MISMATCH, "The action snapshot does not match the grant.", True
        if self.policy.require_unexpired_grant and self._expired(grant, now):
            return ExecutorBlockReason.EXPIRED_GRANT, "The grant expired.", True
        if self.policy.reject_used_grants and grant.used:
            return ExecutorBlockReason.USED_GRANT, "The grant was already used.", True
        session_error = self._session_error(context.session_id, grant)
        if session_error:
            return ExecutorBlockReason.SESSION_MISMATCH, session_error, True
        if not self.policy.is_target_allowed(context.target):
            return ExecutorBlockReason.TARGET_BLOCKED, f"Target {context.target.value} is blocked.", False
        if not self.policy.is_risk_allowed(context.risk):
            return ExecutorBlockReason.RISK_BLOCKED, f"Risk {context.risk.value} is blocked.", False
        action_type = action.metadata.get("action_kind")
        if not isinstance(action_type, str):
            return ExecutorBlockReason.POLICY_BLOCKED, "The action type is not explicitly classified.", False
        if not self.policy.is_action_type_allowed(action_type):
            reason = ExecutorBlockReason.DESTRUCTIVE_ACTION if action_type == "destructive" else ExecutorBlockReason.POLICY_BLOCKED
            return reason, f"Action type {action_type} is blocked.", False
        if self.policy.requires_dry_run(context.risk) and not request.dry_run:
            return ExecutorBlockReason.POLICY_BLOCKED, f"Risk {context.risk.value} requires dry-run.", False
        if not self.policy.validate_timeout(request.timeout_seconds):
            return ExecutorBlockReason.INVALID_PARAMETERS, "The timeout is invalid.", False
        return None

    def _blocked(
        self,
        request: ExecutorRequest,
        reason: ExecutorBlockReason,
        message: str,
        now: float,
        events: tuple[AuditEvent, ...],
    ) -> ExecutorResult:
        attempt = self._attempt(
            request, ExecutorStatus.BLOCKED, now, events=events,
            block_reason=reason, error_summary=message,
        )
        return ExecutorResult(
            success=False,
            request=request,
            attempt=attempt,
            audit_events=events,
            reasoning=self._reasoning(message),
            errors=self._errors(message),
            metadata=self._metadata(request.metadata),
        )

    def _early_failure(
        self,
        message: str,
        reason: ExecutorBlockReason = ExecutorBlockReason.INVALID_PARAMETERS,
        request_id: str | None = None,
    ) -> ExecutorResult:
        attempt = None
        if request_id:
            attempt = ExecutionAttempt(
                attempt_id=f"attempt-{request_id}-001",
                request_id=request_id,
                attempt_number=1,
                status=ExecutorStatus.BLOCKED,
                block_reason=reason,
                error_summary=message,
            )
        return ExecutorResult(success=False, attempt=attempt, errors=self._errors(message))

    def _events(self, request, now: float, specs) -> tuple[AuditEvent, ...]:
        if not self.policy.require_audit_trail:
            return ()
        events = []
        for index, (event_type, message) in enumerate(specs, 1):
            if len(events) >= self.policy.max_audit_events_per_request:
                break
            events.append(AuditEvent(
                event_id=f"audit-{request.request_id}-{index:03d}",
                event_type=event_type,
                request_id=request.request_id,
                session_id=request.context.session_id,
                execution_plan_id=request.context.execution_plan_id,
                action_id=request.context.action_id,
                occurred_at_monotonic=now,
                message=message,
            ))
        return tuple(events)

    def _attempt(
        self, request, status, now, *, events=(), block_reason=None, error_summary=None
    ) -> ExecutionAttempt:
        return ExecutionAttempt(
            attempt_id=f"attempt-{request.request_id}-001",
            request_id=request.request_id,
            attempt_number=1,
            status=status,
            started_at_monotonic=now,
            finished_at_monotonic=now if status == ExecutorStatus.BLOCKED else None,
            block_reason=block_reason,
            error_summary=error_summary,
            audit_events=events,
            metadata=self._metadata(request.metadata),
        )

    def _rollback_plan(self, request: ExecutorRequest) -> RollbackPlan | None:
        if request.action_snapshot.metadata.get("action_kind") != "state_changing":
            return None
        if not self.policy.require_rollback_plan_for_state_change or not self.policy.can_use_rollback():
            return None
        description = request.action_snapshot.metadata.get("rollback_description")
        action_name = request.action_snapshot.metadata.get("rollback_action_name")
        if not isinstance(description, str) or not description.strip() or not isinstance(action_name, str) or not action_name.strip():
            return None
        return RollbackPlan(
            rollback_id=f"rollback-{request.request_id}",
            original_action_id=request.action_snapshot.action_id,
            supported=True,
            description=description,
            rollback_action_name=action_name,
            requires_confirmation=self.policy.require_confirmation_before_rollback,
            requires_human=self.policy.require_human_before_rollback,
        )

    def _session_error(self, session_id: str, grant: ApprovedActionGrant) -> str | None:
        if not self.policy.require_session_match:
            return None
        grant_session = grant.metadata.get("session_id")
        if not isinstance(grant_session, str) or not grant_session.strip():
            return "The grant has no reliable session_id binding."
        if grant_session != session_id:
            return "The grant session_id does not match the execution context."
        return None

    def _metadata(self, metadata: dict[str, object]) -> dict[str, object]:
        return deepcopy(metadata) if self.policy.preserve_metadata else {}

    def _reasoning(self, *messages: str) -> tuple[str, ...]:
        if not self.policy.preserve_reasoning:
            return ()
        return tuple(messages[: self.policy.max_reasoning_messages])

    def _errors(self, *messages: str) -> tuple[str, ...]:
        return tuple(messages[: self.policy.max_errors])

    @staticmethod
    def _request_id(plan: object, action: object, grant: object) -> str | None:
        plan_id = getattr(plan, "plan_id", None)
        action_id = getattr(action, "action_id", None)
        grant_id = getattr(grant, "grant_id", None)
        if all(isinstance(item, str) and item for item in (plan_id, action_id, grant_id)):
            return f"executor-{plan_id}-{action_id}-{grant_id}"
        return None

    @staticmethod
    def _valid_time(value: object) -> bool:
        return isinstance(value, int | float) and not isinstance(value, bool) and value >= 0

    @staticmethod
    def _expired(grant: ApprovedActionGrant, now: float) -> bool:
        return grant.expires_at_monotonic is not None and now >= grant.expires_at_monotonic
