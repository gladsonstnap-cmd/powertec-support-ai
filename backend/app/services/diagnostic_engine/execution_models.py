"""Immutable structural models for future diagnostic execution."""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum


class ExecutionStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class ExecutionTarget(StrEnum):
    LOCAL_MACHINE = "LOCAL_MACHINE"
    REMOTE_AGENT = "REMOTE_AGENT"
    WINDOWS = "WINDOWS"
    LINUX = "LINUX"
    NETWORK = "NETWORK"
    UNKNOWN = "UNKNOWN"


class ExecutionRisk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class ExecutionParameter:
    key: str
    value: object = field(hash=False)
    required: bool
    description: str
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _validate_text("key", self.key)
        object.__setattr__(self, "value", deepcopy(self.value))
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))


@dataclass(frozen=True)
class ExecutionAction:
    action_id: str
    action_name: str
    title: str
    description: str
    target: ExecutionTarget
    status: ExecutionStatus
    risk: ExecutionRisk
    parameters: tuple[ExecutionParameter, ...] = field(hash=False)
    timeout_seconds: int | float
    requires_confirmation: bool
    requires_human: bool
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _validate_text("action_id", self.action_id)
        _validate_text("action_name", self.action_name)
        if (
            not isinstance(self.timeout_seconds, int | float)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be greater than zero")
        object.__setattr__(self, "parameters", tuple(deepcopy(self.parameters)))
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    status: ExecutionStatus
    actions: tuple[ExecutionAction, ...] = field(default=(), hash=False)
    current_action_id: str | None = None
    completed_actions: tuple[str, ...] = ()
    failed_actions: tuple[str, ...] = ()
    cancelled_actions: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict, hash=False)
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_text("plan_id", self.plan_id)
        actions = tuple(sorted(deepcopy(self.actions), key=lambda item: item.action_id))
        action_ids = tuple(action.action_id for action in actions)
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("action_id values must be unique")
        if self.current_action_id is not None and self.current_action_id not in action_ids:
            raise ValueError("current_action_id must reference a plan action")

        state_groups = {
            "completed_actions": tuple(deepcopy(self.completed_actions)),
            "failed_actions": tuple(deepcopy(self.failed_actions)),
            "cancelled_actions": tuple(deepcopy(self.cancelled_actions)),
        }
        for name, identifiers in state_groups.items():
            if len(set(identifiers)) != len(identifiers):
                raise ValueError(f"{name} values must be unique")
            if any(identifier not in action_ids for identifier in identifiers):
                raise ValueError(f"{name} must reference plan actions")
            object.__setattr__(self, name, identifiers)
        completed, failed, cancelled = map(set, state_groups.values())
        if completed & failed or completed & cancelled or failed & cancelled:
            raise ValueError("an action cannot have conflicting terminal states")

        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))


@dataclass(frozen=True)
class ExecutionResult:
    success: bool = False
    execution_plan: ExecutionPlan | None = None
    selected_action: ExecutionAction | None = None
    reasoning: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        if self.success and self.execution_plan is None:
            raise ValueError("success=True requires an execution_plan")
        plan_actions = self.execution_plan.actions if self.execution_plan is not None else ()
        if self.selected_action is not None and self.selected_action not in plan_actions:
            raise ValueError("selected_action must belong to the execution_plan")
        object.__setattr__(self, "execution_plan", deepcopy(self.execution_plan))
        object.__setattr__(self, "selected_action", deepcopy(self.selected_action))
        object.__setattr__(self, "reasoning", tuple(deepcopy(self.reasoning)))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))
        object.__setattr__(self, "metadata", deepcopy(dict(self.metadata)))


def _validate_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
