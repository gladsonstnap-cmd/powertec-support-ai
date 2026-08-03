"""Configuration policy for the deterministic diagnostic planner."""

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class DiagnosticPlannerPolicy:
    max_steps: int = 25
    max_question_steps: int = 10
    max_test_steps: int = 10
    max_confirmation_steps: int = 5
    max_action_steps: int = 5
    max_parallel_alternatives: int = 5
    max_reasoning_messages: int = 20
    max_errors: int = 20
    minimum_step_confidence: float = 0.40
    minimum_plan_confidence: float = 0.50
    require_confirmation_for_medium_risk: bool = False
    require_confirmation_for_high_risk: bool = True
    require_confirmation_for_critical_risk: bool = True
    allow_parallel_alternatives: bool = True
    allow_multiple_active_steps: bool = False
    stop_after_escalation: bool = True
    stop_after_completion: bool = True
    preserve_reasoning: bool = True
    preserve_metadata: bool = True

    def __post_init__(self) -> None:
        limit_names = (
            "max_steps",
            "max_question_steps",
            "max_test_steps",
            "max_confirmation_steps",
            "max_action_steps",
            "max_parallel_alternatives",
            "max_reasoning_messages",
            "max_errors",
        )
        for name in limit_names:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        for name in ("minimum_step_confidence", "minimum_plan_confidence"):
            value = getattr(self, name)
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise ValueError(f"{name} must be a number between 0.0 and 1.0")
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0.0 and 1.0")

        validated_names = {*limit_names, "minimum_step_confidence", "minimum_plan_confidence"}
        for item in fields(self):
            if item.name not in validated_names and not isinstance(getattr(self, item.name), bool):
                raise ValueError(f"{item.name} must be a boolean")
