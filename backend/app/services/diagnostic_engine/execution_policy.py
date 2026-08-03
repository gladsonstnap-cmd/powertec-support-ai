"""Safety policy for the future diagnostic execution layer."""

from dataclasses import dataclass, fields

from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget


@dataclass(frozen=True)
class DiagnosticExecutionPolicy:
    max_actions: int = 20
    max_parameters_per_action: int = 20
    max_reasoning_messages: int = 20
    max_errors: int = 20
    default_timeout_seconds: int = 30
    max_timeout_seconds: int = 300
    max_low_risk_actions: int = 20
    max_medium_risk_actions: int = 10
    max_high_risk_actions: int = 3
    max_critical_risk_actions: int = 1

    allow_local_machine: bool = True
    allow_remote_agent: bool = False
    allow_windows: bool = True
    allow_linux: bool = False
    allow_network: bool = True
    allow_unknown_target: bool = False

    allow_low_risk: bool = True
    allow_medium_risk: bool = True
    allow_high_risk: bool = False
    allow_critical_risk: bool = False

    require_confirmation_for_low_risk: bool = False
    require_confirmation_for_medium_risk: bool = True
    require_confirmation_for_high_risk: bool = True
    require_confirmation_for_critical_risk: bool = True

    require_human_for_high_risk: bool = True
    require_human_for_critical_risk: bool = True

    allow_read_only_actions: bool = True
    allow_state_changing_actions: bool = False
    allow_destructive_actions: bool = False

    preserve_reasoning: bool = True
    preserve_metadata: bool = True
    stop_after_failure: bool = True
    stop_after_blocked: bool = True

    def __post_init__(self) -> None:
        integer_fields = (
            "max_actions",
            "max_parameters_per_action",
            "max_reasoning_messages",
            "max_errors",
            "default_timeout_seconds",
            "max_timeout_seconds",
            "max_low_risk_actions",
            "max_medium_risk_actions",
            "max_high_risk_actions",
            "max_critical_risk_actions",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.default_timeout_seconds > self.max_timeout_seconds:
            raise ValueError("default_timeout_seconds must not exceed max_timeout_seconds")

        for item in fields(self):
            if item.name not in integer_fields and not isinstance(getattr(self, item.name), bool):
                raise ValueError(f"{item.name} must be a boolean")

    def is_target_allowed(self, target: ExecutionTarget) -> bool:
        return {
            ExecutionTarget.LOCAL_MACHINE: self.allow_local_machine,
            ExecutionTarget.REMOTE_AGENT: self.allow_remote_agent,
            ExecutionTarget.WINDOWS: self.allow_windows,
            ExecutionTarget.LINUX: self.allow_linux,
            ExecutionTarget.NETWORK: self.allow_network,
            ExecutionTarget.UNKNOWN: self.allow_unknown_target,
        }[target]

    def is_risk_allowed(self, risk: ExecutionRisk) -> bool:
        return {
            ExecutionRisk.LOW: self.allow_low_risk,
            ExecutionRisk.MEDIUM: self.allow_medium_risk,
            ExecutionRisk.HIGH: self.allow_high_risk,
            ExecutionRisk.CRITICAL: self.allow_critical_risk,
        }[risk]

    def requires_confirmation(self, risk: ExecutionRisk) -> bool:
        return {
            ExecutionRisk.LOW: self.require_confirmation_for_low_risk,
            ExecutionRisk.MEDIUM: self.require_confirmation_for_medium_risk,
            ExecutionRisk.HIGH: self.require_confirmation_for_high_risk,
            ExecutionRisk.CRITICAL: self.require_confirmation_for_critical_risk,
        }[risk]

    def requires_human(self, risk: ExecutionRisk) -> bool:
        return {
            ExecutionRisk.LOW: False,
            ExecutionRisk.MEDIUM: False,
            ExecutionRisk.HIGH: self.require_human_for_high_risk,
            ExecutionRisk.CRITICAL: self.require_human_for_critical_risk,
        }[risk]

    def max_actions_for_risk(self, risk: ExecutionRisk) -> int:
        return {
            ExecutionRisk.LOW: self.max_low_risk_actions,
            ExecutionRisk.MEDIUM: self.max_medium_risk_actions,
            ExecutionRisk.HIGH: self.max_high_risk_actions,
            ExecutionRisk.CRITICAL: self.max_critical_risk_actions,
        }[risk]

    def validate_timeout(self, timeout_seconds: int) -> bool:
        return (
            isinstance(timeout_seconds, int)
            and not isinstance(timeout_seconds, bool)
            and 0 < timeout_seconds <= self.max_timeout_seconds
        )
