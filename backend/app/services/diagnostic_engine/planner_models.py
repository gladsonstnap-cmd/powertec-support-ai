"""Immutable data models for deterministic diagnostic plans."""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum

from app.services.diagnostic_engine.decision_models import DecisionType
from app.services.diagnostic_engine.enums import RiskLevel


class PlanStepType(StrEnum):
    ASK_QUESTION = "ASK_QUESTION"
    RUN_TEST = "RUN_TEST"
    VERIFY_RESULT = "VERIFY_RESULT"
    REQUEST_CONFIRMATION = "REQUEST_CONFIRMATION"
    RECOMMEND_ACTION = "RECOMMEND_ACTION"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"
    COMPLETE = "COMPLETE"


class PlanStepStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class DiagnosticPlanStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    WAITING_USER = "WAITING_USER"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class PlanCondition:
    key: str
    operator: str
    expected_value: object
    description: str
    required: bool = True
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_text("key", self.key)
        _validate_text("operator", self.operator)
        _validate_text("description", self.description)
        object.__setattr__(self, "expected_value", deepcopy(self.expected_value))
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    step_type: PlanStepType
    status: PlanStepStatus
    title: str
    instruction: str
    sequence: int
    incident_id: str | None
    confidence: float
    risk_level: RiskLevel
    requires_human: bool
    requires_confirmation: bool
    question: str | None = None
    recommended_test: str | None = None
    recommended_action: str | None = None
    preconditions: tuple[PlanCondition, ...] = ()
    success_conditions: tuple[PlanCondition, ...] = ()
    failure_conditions: tuple[PlanCondition, ...] = ()
    depends_on: tuple[str, ...] = ()
    evidence_required: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_text("step_id", self.step_id)
        _validate_text("title", self.title)
        _validate_text("instruction", self.instruction)
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        _validate_confidence(self.confidence)

        dependencies = tuple(deepcopy(self.depends_on))
        if any(not isinstance(item, str) or not item.strip() for item in dependencies):
            raise ValueError("depends_on references must not be empty")
        if self.step_id in dependencies:
            raise ValueError("a step cannot depend on itself")
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("depends_on references must be unique")

        for name in ("preconditions", "success_conditions", "failure_conditions", "evidence_required"):
            object.__setattr__(self, name, tuple(deepcopy(getattr(self, name))))
        object.__setattr__(self, "depends_on", dependencies)
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))


@dataclass(frozen=True)
class DiagnosticPlan:
    plan_id: str
    status: DiagnosticPlanStatus
    incident_id: str | None
    primary_hypothesis_id: str | None
    confidence: float
    steps: tuple[PlanStep, ...] = ()
    current_step_id: str | None = None
    completed_step_ids: tuple[str, ...] = ()
    skipped_step_ids: tuple[str, ...] = ()
    failed_step_ids: tuple[str, ...] = ()
    created_from_decision_type: DecisionType | None = None
    requires_human: bool = False
    risk_level: RiskLevel = RiskLevel.LOW
    reasoning: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_text("plan_id", self.plan_id)
        _validate_confidence(self.confidence)
        steps = tuple(sorted(deepcopy(self.steps), key=lambda item: (item.sequence, item.step_id)))
        step_ids = tuple(step.step_id for step in steps)
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("step_id values must be unique")
        if self.current_step_id is not None and self.current_step_id not in step_ids:
            raise ValueError("current_step_id must reference a plan step")

        state_groups = {
            "completed_step_ids": tuple(deepcopy(self.completed_step_ids)),
            "skipped_step_ids": tuple(deepcopy(self.skipped_step_ids)),
            "failed_step_ids": tuple(deepcopy(self.failed_step_ids)),
        }
        for name, identifiers in state_groups.items():
            if len(set(identifiers)) != len(identifiers):
                raise ValueError(f"{name} values must be unique")
            if any(identifier not in step_ids for identifier in identifiers):
                raise ValueError(f"{name} must reference plan steps")
            object.__setattr__(self, name, identifiers)
        completed, skipped, failed = map(set, state_groups.values())
        if completed & skipped or completed & failed or skipped & failed:
            raise ValueError("a step cannot have conflicting terminal states")

        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "reasoning", tuple(deepcopy(self.reasoning)))
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))


@dataclass(frozen=True)
class DiagnosticPlanResult:
    plan: DiagnosticPlan | None = None
    success: bool = False
    selected_step: PlanStep | None = None
    alternatives: tuple[PlanStep, ...] = ()
    reasoning: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.success and self.plan is None:
            raise ValueError("success=True requires a plan")
        plan_steps = self.plan.steps if self.plan is not None else ()
        if self.selected_step is not None and self.selected_step not in plan_steps:
            raise ValueError("selected_step must belong to the plan")
        alternatives = tuple(deepcopy(self.alternatives))
        alternative_ids = tuple(step.step_id for step in alternatives)
        if len(set(alternative_ids)) != len(alternative_ids):
            raise ValueError("alternatives must not contain duplicates")
        if self.selected_step is not None and self.selected_step.step_id in alternative_ids:
            raise ValueError("selected_step must not be repeated in alternatives")
        object.__setattr__(self, "plan", deepcopy(self.plan))
        object.__setattr__(self, "selected_step", deepcopy(self.selected_step))
        object.__setattr__(self, "alternatives", alternatives)
        object.__setattr__(self, "reasoning", tuple(deepcopy(self.reasoning)))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))


def _validate_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")


def _validate_confidence(value: float) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool) or not 0.0 <= value <= 1.0:
        raise ValueError("confidence must be a number between 0.0 and 1.0")
