"""Conservative policy settings for diagnostic action approvals."""

from dataclasses import dataclass, fields

from app.services.diagnostic_engine.approval_models import ApprovalScope, ApprovalStatus, ApprovalType
from app.services.diagnostic_engine.execution_models import ExecutionRisk


@dataclass(frozen=True)
class DiagnosticApprovalPolicy:
    """Immutable limits and authorization rules for action approvals."""

    max_pending_requests: int = 20
    max_requests_per_session: int = 50
    max_reasoning_messages: int = 20
    max_errors: int = 20
    default_approval_ttl_seconds: int = 300
    max_approval_ttl_seconds: int = 3600

    single_use_grants: bool = True
    allow_reuse_after_rejection: bool = False
    allow_reuse_after_expiration: bool = True
    allow_reuse_after_cancellation: bool = False
    allow_scope_single_action: bool = True
    allow_scope_execution_plan: bool = False
    allow_scope_session: bool = False
    allow_user_confirmation: bool = True
    allow_human_technician: bool = True
    allow_administrator: bool = True
    allow_policy_override: bool = False
    require_approval_for_low_risk: bool = False
    require_approval_for_medium_risk: bool = True
    require_approval_for_high_risk: bool = True
    require_approval_for_critical_risk: bool = True
    require_human_for_low_risk: bool = False
    require_human_for_medium_risk: bool = False
    require_human_for_high_risk: bool = True
    require_human_for_critical_risk: bool = True
    require_admin_for_low_risk: bool = False
    require_admin_for_medium_risk: bool = False
    require_admin_for_high_risk: bool = False
    require_admin_for_critical_risk: bool = True
    allow_approval_of_blocked_action: bool = False
    allow_approval_of_destructive_action: bool = False
    allow_approval_of_unknown_target: bool = False
    preserve_reasoning: bool = True
    preserve_metadata: bool = True
    reject_expired_requests: bool = True
    reject_used_grants: bool = True

    def __post_init__(self) -> None:
        integer_fields = {
            "max_pending_requests",
            "max_requests_per_session",
            "max_reasoning_messages",
            "max_errors",
            "default_approval_ttl_seconds",
            "max_approval_ttl_seconds",
        }
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in integer_fields:
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    raise ValueError(f"{field.name} must be a positive integer")
            elif not isinstance(value, bool):
                raise ValueError(f"{field.name} must be a boolean")

        if self.default_approval_ttl_seconds > self.max_approval_ttl_seconds:
            raise ValueError("default_approval_ttl_seconds must not exceed max_approval_ttl_seconds")

    def is_scope_allowed(self, scope: ApprovalScope) -> bool:
        return {
            ApprovalScope.SINGLE_ACTION: self.allow_scope_single_action,
            ApprovalScope.EXECUTION_PLAN: self.allow_scope_execution_plan,
            ApprovalScope.SESSION: self.allow_scope_session,
        }[scope]

    def is_actor_type_allowed(self, actor_type: ApprovalType) -> bool:
        return {
            ApprovalType.USER_CONFIRMATION: self.allow_user_confirmation,
            ApprovalType.HUMAN_TECHNICIAN: self.allow_human_technician,
            ApprovalType.ADMINISTRATOR: self.allow_administrator,
            ApprovalType.POLICY_OVERRIDE: self.allow_policy_override,
        }[actor_type]

    def requires_approval(self, risk: ExecutionRisk) -> bool:
        return {
            ExecutionRisk.LOW: self.require_approval_for_low_risk,
            ExecutionRisk.MEDIUM: self.require_approval_for_medium_risk,
            ExecutionRisk.HIGH: self.require_approval_for_high_risk,
            ExecutionRisk.CRITICAL: self.require_approval_for_critical_risk,
        }[risk]

    def requires_human(self, risk: ExecutionRisk) -> bool:
        return {
            ExecutionRisk.LOW: self.require_human_for_low_risk,
            ExecutionRisk.MEDIUM: self.require_human_for_medium_risk,
            ExecutionRisk.HIGH: self.require_human_for_high_risk,
            ExecutionRisk.CRITICAL: self.require_human_for_critical_risk,
        }[risk]

    def requires_admin(self, risk: ExecutionRisk) -> bool:
        return {
            ExecutionRisk.LOW: self.require_admin_for_low_risk,
            ExecutionRisk.MEDIUM: self.require_admin_for_medium_risk,
            ExecutionRisk.HIGH: self.require_admin_for_high_risk,
            ExecutionRisk.CRITICAL: self.require_admin_for_critical_risk,
        }[risk]

    def validate_ttl(self, ttl_seconds: int) -> bool:
        return (
            isinstance(ttl_seconds, int)
            and not isinstance(ttl_seconds, bool)
            and 0 < ttl_seconds <= self.max_approval_ttl_seconds
        )

    def can_reuse_after(self, status: ApprovalStatus) -> bool:
        return {
            ApprovalStatus.PENDING: False,
            ApprovalStatus.APPROVED: False,
            ApprovalStatus.REJECTED: self.allow_reuse_after_rejection,
            ApprovalStatus.EXPIRED: self.allow_reuse_after_expiration,
            ApprovalStatus.CANCELLED: self.allow_reuse_after_cancellation,
            ApprovalStatus.USED: False,
        }[status]
