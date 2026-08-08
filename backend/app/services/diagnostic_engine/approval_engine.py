"""Deterministic authorization workflow for diagnostic execution actions."""

from copy import deepcopy
from dataclasses import replace

from app.services.diagnostic_engine.approval_models import (
    ActionApprovalRequest,
    ApprovalActor,
    ApprovalDecision,
    ApprovalResult,
    ApprovalScope,
    ApprovalStatus,
    ApprovalType,
    ApprovedActionGrant,
)
from app.services.diagnostic_engine.approval_policy import DiagnosticApprovalPolicy
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction,
    ExecutionPlan,
    ExecutionRisk,
    ExecutionStatus,
    ExecutionTarget,
)


_ACTOR_AUTHORITY = {
    ApprovalType.USER_CONFIRMATION: 1,
    ApprovalType.HUMAN_TECHNICIAN: 2,
    ApprovalType.ADMINISTRATOR: 3,
}
_SECRET_TERMS = (
    "password", "senha", "token", "secret", "segredo", "credential", "credencial",
    "api_key", "authorization",
)


class DiagnosticApprovalEngine:
    """Create and validate approvals without executing or mutating actions."""

    def __init__(self, policy: DiagnosticApprovalPolicy | None = None) -> None:
        self.policy = policy if policy is not None else DiagnosticApprovalPolicy()

    def create_request(
        self,
        execution_plan: ExecutionPlan,
        action: ExecutionAction,
        session_id: str | None = None,
        requested_by: ApprovalActor | None = None,
        scope: ApprovalScope = ApprovalScope.SINGLE_ACTION,
        now_monotonic: float = 0.0,
        ttl_seconds: int | None = None,
    ) -> ApprovalResult:
        if not isinstance(execution_plan, ExecutionPlan):
            return self._failure("execution_plan must be an ExecutionPlan")
        if not isinstance(action, ExecutionAction):
            return self._failure("action must be an ExecutionAction")
        if not isinstance(execution_plan.status, ExecutionStatus):
            return self._failure("execution_plan.status must be an ExecutionStatus")
        if not isinstance(action.status, ExecutionStatus):
            return self._failure("action.status must be an ExecutionStatus")
        if not isinstance(action.target, ExecutionTarget):
            return self._failure("action.target must be an ExecutionTarget")
        if not isinstance(action.risk, ExecutionRisk):
            return self._failure("action.risk must be an ExecutionRisk")
        if not self._valid_time(now_monotonic):
            return self._failure("now_monotonic must be a number")
        if not isinstance(scope, ApprovalScope):
            return self._failure("scope must be an ApprovalScope")
        if requested_by is not None and not isinstance(requested_by, ApprovalActor):
            return self._failure("requested_by must be an ApprovalActor")
        plan_action = next((item for item in execution_plan.actions if item.action_id == action.action_id), None)
        if plan_action is None or plan_action != action:
            return self._failure("The action does not belong to the execution plan.")
        if not self.policy.is_scope_allowed(scope):
            return self._failure(f"Scope {scope.value} is blocked by approval policy.")
        if action.target == ExecutionTarget.UNKNOWN and not self.policy.allow_approval_of_unknown_target:
            return self._failure("Target UNKNOWN cannot be approved.")
        if action.status == ExecutionStatus.BLOCKED and not self.policy.allow_approval_of_blocked_action:
            return self._failure("A blocked action cannot be approved.")
        if self._is_destructive(action) and not self.policy.allow_approval_of_destructive_action:
            return self._failure("A destructive action cannot be approved.")
        if not self.policy.requires_approval(action.risk):
            return self._failure(f"Risk {action.risk.value} does not require approval.")

        required_actor_type = self._required_actor(action.risk)
        if not self.policy.is_actor_type_allowed(required_actor_type):
            return self._failure(f"Required actor type {required_actor_type.value} is blocked by approval policy.")
        ttl = self.policy.default_approval_ttl_seconds if ttl_seconds is None else ttl_seconds
        if not self.policy.validate_ttl(ttl):
            return self._failure("ttl_seconds must be a positive integer within the configured maximum.")

        safe_action = self._safe_action(action)
        reason = f"A ação de risco {action.risk.value} exige aprovação."
        request = ActionApprovalRequest(
            approval_id=f"approval-{execution_plan.plan_id}-{action.action_id}",
            scope=scope,
            execution_plan_id=execution_plan.plan_id,
            action_id=action.action_id,
            session_id=session_id,
            requested_by=requested_by,
            required_actor_type=required_actor_type,
            status=ApprovalStatus.PENDING,
            risk=action.risk,
            action_snapshot=safe_action,
            reason=reason,
            created_at_monotonic=now_monotonic,
            expires_at_monotonic=now_monotonic + ttl,
            metadata=self._safe_metadata(action.metadata) if self.policy.preserve_metadata else {},
        )
        return ApprovalResult(
            success=True,
            request=request,
            reasoning=self._reasoning(reason, f"A aprovação requer {required_actor_type.value}."),
            metadata=deepcopy(request.metadata),
        )

    def decide(
        self,
        request: ActionApprovalRequest,
        status: ApprovalStatus,
        decided_by: ApprovalActor,
        now_monotonic: float,
        reason: str | None = None,
    ) -> ApprovalResult:
        if not isinstance(request, ActionApprovalRequest):
            return self._failure("request must be an ActionApprovalRequest")
        allowed_statuses = {
            ApprovalStatus.APPROVED, ApprovalStatus.REJECTED,
            ApprovalStatus.CANCELLED, ApprovalStatus.EXPIRED,
        }
        if status not in allowed_statuses:
            return self._failure("Decision status must be APPROVED, REJECTED, CANCELLED, or EXPIRED.")
        if not isinstance(decided_by, ApprovalActor):
            return self._failure("decided_by must be an ApprovalActor")
        if not self._valid_time(now_monotonic):
            return self._failure("now_monotonic must be a number")
        consistency_error = self._request_error(request)
        if consistency_error:
            return self._failure(consistency_error, request=request)
        if request.status != ApprovalStatus.PENDING:
            return self._failure("Only a PENDING request can be decided.", request=request)
        if self._expired(request.expires_at_monotonic, now_monotonic):
            return self._failure("A solicitação expirou.", request=request)
        if not self.policy.is_actor_type_allowed(decided_by.actor_type):
            return self._failure(f"Actor type {decided_by.actor_type.value} is blocked by approval policy.", request=request)
        if status == ApprovalStatus.APPROVED and not self._actor_satisfies(decided_by.actor_type, request.required_actor_type):
            return self._failure("The actor does not have the required approval authority.", request=request)

        decision = ApprovalDecision(
            approval_id=request.approval_id,
            status=status,
            decided_by=decided_by,
            decided_at_monotonic=now_monotonic,
            reason=reason,
            metadata=self._safe_metadata(request.metadata) if self.policy.preserve_metadata else {},
        )
        message = {
            ApprovalStatus.APPROVED: "A solicitação foi aprovada; nenhuma ação foi executada.",
            ApprovalStatus.REJECTED: "A solicitação foi rejeitada.",
            ApprovalStatus.CANCELLED: "A solicitação foi cancelada.",
            ApprovalStatus.EXPIRED: "A solicitação foi marcada como expirada.",
        }[status]
        return ApprovalResult(
            success=True,
            request=request,
            decision=decision,
            reasoning=self._reasoning(message),
            metadata=deepcopy(decision.metadata),
        )

    def create_grant(
        self,
        request: ActionApprovalRequest,
        decision: ApprovalDecision,
        action: ExecutionAction,
        now_monotonic: float,
    ) -> ApprovalResult:
        if not all((isinstance(request, ActionApprovalRequest), isinstance(decision, ApprovalDecision), isinstance(action, ExecutionAction))):
            return self._failure("request, decision, and action must use approval model types")
        if not self._valid_time(now_monotonic):
            return self._failure("now_monotonic must be a number")
        if decision.status != ApprovalStatus.APPROVED:
            return self._failure("Only an APPROVED decision can create a grant.", request=request, decision=decision)
        if decision.approval_id != request.approval_id:
            return self._failure("The decision approval_id does not match the request.", request=request)
        if decision.decided_by is None or not self.policy.is_actor_type_allowed(decision.decided_by.actor_type):
            return self._failure("The approving actor is not allowed.", request=request, decision=decision)
        if not self._actor_satisfies(decision.decided_by.actor_type, request.required_actor_type):
            return self._failure("The approving actor lacks required authority.", request=request, decision=decision)
        if request.action_id != action.action_id:
            return self._failure("The action_id does not match the approval request.", request=request, decision=decision)
        if request.action_snapshot != self._safe_action(action):
            return self._failure("O snapshot da ação não corresponde à autorização.", request=request, decision=decision)
        if self._expired(request.expires_at_monotonic, now_monotonic):
            return self._failure("A solicitação expirou.", request=request, decision=decision)
        if action.status == ExecutionStatus.BLOCKED and not self.policy.allow_approval_of_blocked_action:
            return self._failure("A blocked action cannot receive a grant.", request=request, decision=decision)
        if self._is_destructive(action) and not self.policy.allow_approval_of_destructive_action:
            return self._failure("A destructive action cannot receive a grant.", request=request, decision=decision)
        if action.target == ExecutionTarget.UNKNOWN and not self.policy.allow_approval_of_unknown_target:
            return self._failure("Target UNKNOWN cannot receive a grant.", request=request, decision=decision)

        grant = ApprovedActionGrant(
            grant_id=f"grant-{request.approval_id}-{action.action_id}",
            approval_id=request.approval_id,
            execution_plan_id=request.execution_plan_id,
            action_id=action.action_id,
            action_snapshot=request.action_snapshot,
            approved_by=decision.decided_by,
            approved_at_monotonic=decision.decided_at_monotonic,
            expires_at_monotonic=request.expires_at_monotonic,
            single_use=self.policy.single_use_grants,
            metadata=self._safe_metadata(request.metadata) if self.policy.preserve_metadata else {},
        )
        return ApprovalResult(
            success=True, request=request, decision=decision, grant=grant,
            reasoning=self._reasoning("O grant autoriza somente o snapshot aprovado."),
            metadata=deepcopy(grant.metadata),
        )

    def validate_grant(
        self,
        grant: ApprovedActionGrant,
        action: ExecutionAction,
        now_monotonic: float,
    ) -> ApprovalResult:
        error = self._grant_error(grant, action, now_monotonic)
        if error:
            return self._failure(error)
        return self._grant_result(grant, "O grant autoriza esta ação específica.")

    def consume_grant(
        self,
        grant: ApprovedActionGrant,
        action: ExecutionAction,
        now_monotonic: float,
    ) -> ApprovalResult:
        error = self._grant_error(grant, action, now_monotonic)
        if error:
            return self._failure(error)
        consumed = replace(grant, used=True)
        return self._grant_result(consumed, "O grant foi marcado como utilizado; nenhuma ação foi executada.")

    def can_create_replacement_request(
        self,
        previous_request: ActionApprovalRequest,
        previous_decision: ApprovalDecision,
    ) -> bool:
        return (
            isinstance(previous_request, ActionApprovalRequest)
            and isinstance(previous_decision, ApprovalDecision)
            and previous_request.approval_id == previous_decision.approval_id
            and self.policy.can_reuse_after(previous_decision.status)
        )

    def _required_actor(self, risk: ExecutionRisk) -> ApprovalType:
        if self.policy.requires_admin(risk):
            return ApprovalType.ADMINISTRATOR
        if self.policy.requires_human(risk):
            return ApprovalType.HUMAN_TECHNICIAN
        return ApprovalType.USER_CONFIRMATION

    def _actor_satisfies(self, actual: ApprovalType, required: ApprovalType) -> bool:
        if actual == ApprovalType.POLICY_OVERRIDE:
            return self.policy.allow_policy_override and required != ApprovalType.ADMINISTRATOR
        if required == ApprovalType.POLICY_OVERRIDE:
            return actual == required and self.policy.allow_policy_override
        return _ACTOR_AUTHORITY.get(actual, 0) >= _ACTOR_AUTHORITY.get(required, 0)

    def _grant_error(self, grant: object, action: object, now: object) -> str | None:
        if not isinstance(grant, ApprovedActionGrant):
            return "grant must be an ApprovedActionGrant"
        if not isinstance(action, ExecutionAction):
            return "action must be an ExecutionAction"
        if not self._valid_time(now):
            return "now_monotonic must be a number"
        if grant.action_id != action.action_id:
            return "The grant action_id does not match the action."
        if grant.action_snapshot != self._safe_action(action):
            return "O snapshot da ação não corresponde à autorização."
        if not grant.execution_plan_id:
            return "The grant execution_plan_id is invalid."
        if self._expired(grant.expires_at_monotonic, now):
            return "O grant expirou."
        if grant.used and (grant.single_use or self.policy.reject_used_grants):
            return "O grant já foi utilizado."
        if grant.single_use != self.policy.single_use_grants:
            return "The grant single-use rule does not match approval policy."
        if not self.policy.is_actor_type_allowed(grant.approved_by.actor_type):
            return "The grant approving actor is not allowed."
        return None

    def _request_error(self, request: ActionApprovalRequest) -> str | None:
        if request.action_snapshot is None or request.action_id != request.action_snapshot.action_id:
            return "The approval request has an inconsistent action snapshot."
        if request.risk != request.action_snapshot.risk:
            return "The approval request has an inconsistent risk."
        if not self.policy.is_scope_allowed(request.scope):
            return "The approval request scope is blocked by policy."
        return None

    @staticmethod
    def _is_destructive(action: ExecutionAction) -> bool:
        return action.metadata.get("action_kind") == "destructive"

    @classmethod
    def _safe_action(cls, action: ExecutionAction) -> ExecutionAction:
        return replace(action, metadata=cls._safe_metadata(action.metadata))

    @classmethod
    def _safe_metadata(cls, metadata: dict[str, object]) -> dict[str, object]:
        safe = {}
        for key, value in deepcopy(dict(metadata)).items():
            normalized = str(key).strip().lower()
            if any(term in normalized for term in _SECRET_TERMS) or cls._contains_secret(value):
                continue
            safe[key] = cls._safe_metadata(value) if isinstance(value, dict) else value
        return safe

    @classmethod
    def _contains_secret(cls, value: object) -> bool:
        if isinstance(value, str):
            normalized = value.strip().lower()
            return any(term in normalized for term in _SECRET_TERMS)
        if isinstance(value, dict):
            return any(
                any(term in str(key).lower() for term in _SECRET_TERMS) or cls._contains_secret(item)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple, set)):
            return any(cls._contains_secret(item) for item in value)
        return False

    @staticmethod
    def _valid_time(value: object) -> bool:
        return isinstance(value, int | float) and not isinstance(value, bool)

    @staticmethod
    def _expired(expires_at: float | None, now: float) -> bool:
        return expires_at is not None and now >= expires_at

    def _reasoning(self, *messages: str) -> tuple[str, ...]:
        if not self.policy.preserve_reasoning:
            return ()
        return tuple(messages[: self.policy.max_reasoning_messages])

    def _failure(
        self,
        error: str,
        request: ActionApprovalRequest | None = None,
        decision: ApprovalDecision | None = None,
    ) -> ApprovalResult:
        return ApprovalResult(
            success=False,
            request=request,
            decision=decision,
            errors=(error,)[: self.policy.max_errors],
        )

    def _grant_result(self, grant: ApprovedActionGrant, message: str) -> ApprovalResult:
        decision = ApprovalDecision(
            approval_id=grant.approval_id,
            status=ApprovalStatus.APPROVED,
            decided_by=grant.approved_by,
            decided_at_monotonic=grant.approved_at_monotonic,
            reason="Grant approval record.",
            metadata=self._safe_metadata(grant.metadata) if self.policy.preserve_metadata else {},
        )
        return ApprovalResult(
            success=True,
            decision=decision,
            grant=grant,
            reasoning=self._reasoning(message),
            metadata=deepcopy(decision.metadata),
        )
