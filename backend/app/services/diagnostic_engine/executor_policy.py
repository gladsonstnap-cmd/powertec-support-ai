"""Conservative configuration for a future diagnostic executor."""

from dataclasses import dataclass, fields

from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.executor_models import ExecutorStatus


@dataclass(frozen=True)
class DiagnosticExecutorPolicy:
    """Immutable limits and safety switches; performs no execution."""

    max_attempts_per_action: int = 1
    max_total_attempts_per_session: int = 20
    max_audit_events_per_request: int = 100
    max_reasoning_messages: int = 20
    max_errors: int = 20
    default_timeout_seconds: int = 30
    max_timeout_seconds: int = 300

    require_valid_grant: bool = True
    require_unexpired_grant: bool = True
    reject_used_grants: bool = True
    require_action_snapshot_match: bool = True
    require_plan_match: bool = True
    require_session_match: bool = True
    allow_local_execution: bool = False
    allow_remote_execution: bool = False
    allow_windows_target: bool = True
    allow_linux_target: bool = False
    allow_network_target: bool = True
    allow_unknown_target: bool = False
    allow_remote_agent_target: bool = False
    allow_low_risk: bool = True
    allow_medium_risk: bool = False
    allow_high_risk: bool = False
    allow_critical_risk: bool = False
    require_dry_run_for_low_risk: bool = False
    require_dry_run_for_medium_risk: bool = True
    require_dry_run_for_high_risk: bool = True
    require_dry_run_for_critical_risk: bool = True
    allow_read_only_actions: bool = True
    allow_state_changing_actions: bool = False
    allow_destructive_actions: bool = False
    require_audit_trail: bool = True
    require_validation_event: bool = True
    require_authorization_event: bool = True
    require_start_event: bool = True
    require_terminal_event: bool = True
    allow_retry_after_failure: bool = False
    allow_retry_after_timeout: bool = False
    allow_retry_after_blocked: bool = False
    allow_rollback: bool = False
    require_rollback_plan_for_state_change: bool = True
    require_confirmation_before_rollback: bool = True
    require_human_before_rollback: bool = True
    stop_after_failure: bool = True
    stop_after_timeout: bool = True
    stop_after_blocked: bool = True
    preserve_reasoning: bool = True
    preserve_metadata: bool = True

    def __post_init__(self) -> None:
        integer_fields = {
            "max_attempts_per_action",
            "max_total_attempts_per_session",
            "max_audit_events_per_request",
            "max_reasoning_messages",
            "max_errors",
            "default_timeout_seconds",
            "max_timeout_seconds",
        }
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name in integer_fields:
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    raise ValueError(f"{item.name} must be a positive integer")
            elif not isinstance(value, bool):
                raise ValueError(f"{item.name} must be a boolean")
        if self.default_timeout_seconds > self.max_timeout_seconds:
            raise ValueError("default_timeout_seconds must not exceed max_timeout_seconds")

    def is_target_allowed(self, target: ExecutionTarget) -> bool:
        return {
            ExecutionTarget.LOCAL_MACHINE: self.allow_local_execution,
            ExecutionTarget.WINDOWS: self.allow_windows_target,
            ExecutionTarget.LINUX: self.allow_linux_target,
            ExecutionTarget.NETWORK: self.allow_network_target,
            ExecutionTarget.REMOTE_AGENT: self.allow_remote_agent_target,
            ExecutionTarget.UNKNOWN: self.allow_unknown_target,
        }[target]

    def is_risk_allowed(self, risk: ExecutionRisk) -> bool:
        return {
            ExecutionRisk.LOW: self.allow_low_risk,
            ExecutionRisk.MEDIUM: self.allow_medium_risk,
            ExecutionRisk.HIGH: self.allow_high_risk,
            ExecutionRisk.CRITICAL: self.allow_critical_risk,
        }[risk]

    def requires_dry_run(self, risk: ExecutionRisk) -> bool:
        return {
            ExecutionRisk.LOW: self.require_dry_run_for_low_risk,
            ExecutionRisk.MEDIUM: self.require_dry_run_for_medium_risk,
            ExecutionRisk.HIGH: self.require_dry_run_for_high_risk,
            ExecutionRisk.CRITICAL: self.require_dry_run_for_critical_risk,
        }[risk]

    def is_action_type_allowed(self, action_type: str) -> bool:
        return {
            "read_only": self.allow_read_only_actions,
            "state_changing": self.allow_state_changing_actions,
            "destructive": self.allow_destructive_actions,
        }.get(action_type, False)

    def validate_timeout(self, timeout_seconds: int) -> bool:
        return (
            isinstance(timeout_seconds, int)
            and not isinstance(timeout_seconds, bool)
            and 0 < timeout_seconds <= self.max_timeout_seconds
        )

    def can_retry_after(self, status: ExecutorStatus) -> bool:
        return {
            ExecutorStatus.FAILED: self.allow_retry_after_failure,
            ExecutorStatus.TIMED_OUT: self.allow_retry_after_timeout,
            ExecutorStatus.BLOCKED: self.allow_retry_after_blocked,
        }.get(status, False)

    def can_use_rollback(self) -> bool:
        return self.allow_rollback

    def max_attempts_for_request(self) -> int:
        return self.max_attempts_per_action
