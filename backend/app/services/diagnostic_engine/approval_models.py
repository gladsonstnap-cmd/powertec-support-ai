"""Immutable approval and remote-action authorization models."""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum

from app.services.diagnostic_engine.execution_models import ExecutionAction, ExecutionRisk


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    USED = "USED"


class ApprovalType(StrEnum):
    USER_CONFIRMATION = "USER_CONFIRMATION"
    HUMAN_TECHNICIAN = "HUMAN_TECHNICIAN"
    ADMINISTRATOR = "ADMINISTRATOR"
    POLICY_OVERRIDE = "POLICY_OVERRIDE"


class ApprovalScope(StrEnum):
    SINGLE_ACTION = "SINGLE_ACTION"
    EXECUTION_PLAN = "EXECUTION_PLAN"
    SESSION = "SESSION"


@dataclass(frozen=True)
class ApprovalActor:
    actor_id: str
    actor_type: ApprovalType
    display_name: str | None = None
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _validate_text("actor_id", self.actor_id)
        _validate_enum("actor_type", self.actor_type, ApprovalType)
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class ActionApprovalRequest:
    approval_id: str
    scope: ApprovalScope
    execution_plan_id: str
    action_id: str | None
    session_id: str | None
    requested_by: ApprovalActor | None
    required_actor_type: ApprovalType
    status: ApprovalStatus
    risk: ExecutionRisk
    action_snapshot: ExecutionAction | None
    reason: str
    created_at_monotonic: float
    expires_at_monotonic: float | None
    metadata: dict[str, object] = field(default_factory=dict, hash=False)
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_text("approval_id", self.approval_id)
        _validate_text("execution_plan_id", self.execution_plan_id)
        _validate_enum("scope", self.scope, ApprovalScope)
        _validate_enum("required_actor_type", self.required_actor_type, ApprovalType)
        _validate_enum("status", self.status, ApprovalStatus)
        _validate_enum("risk", self.risk, ExecutionRisk)
        if self.requested_by is not None and not isinstance(self.requested_by, ApprovalActor):
            raise ValueError("requested_by must be an ApprovalActor")
        if self.action_snapshot is not None and not isinstance(self.action_snapshot, ExecutionAction):
            raise ValueError("action_snapshot must be an ExecutionAction")
        _validate_timestamp("created_at_monotonic", self.created_at_monotonic)
        _validate_expiration(
            self.created_at_monotonic,
            self.expires_at_monotonic,
            "created_at_monotonic",
        )
        if self.scope == ApprovalScope.SINGLE_ACTION:
            _validate_text("action_id", self.action_id)
        if self.action_snapshot is not None and self.action_snapshot.action_id != self.action_id:
            raise ValueError("action_snapshot must correspond to action_id")
        object.__setattr__(self, "requested_by", deepcopy(self.requested_by))
        object.__setattr__(self, "action_snapshot", deepcopy(self.action_snapshot))
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))


@dataclass(frozen=True)
class ApprovalDecision:
    approval_id: str
    status: ApprovalStatus
    decided_by: ApprovalActor | None
    decided_at_monotonic: float
    reason: str | None
    metadata: dict[str, object] = field(default_factory=dict, hash=False)
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_text("approval_id", self.approval_id)
        _validate_enum("status", self.status, ApprovalStatus)
        allowed = {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.CANCELLED,
            ApprovalStatus.EXPIRED,
        }
        if self.status not in allowed:
            raise ValueError("status must be APPROVED, REJECTED, CANCELLED, or EXPIRED")
        if self.decided_by is not None and not isinstance(self.decided_by, ApprovalActor):
            raise ValueError("decided_by must be an ApprovalActor")
        _validate_timestamp("decided_at_monotonic", self.decided_at_monotonic)
        object.__setattr__(self, "decided_by", deepcopy(self.decided_by))
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))


@dataclass(frozen=True)
class ApprovedActionGrant:
    grant_id: str
    approval_id: str
    execution_plan_id: str
    action_id: str
    action_snapshot: ExecutionAction
    approved_by: ApprovalActor
    approved_at_monotonic: float
    expires_at_monotonic: float | None
    single_use: bool = True
    used: bool = False
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        for name in ("grant_id", "approval_id", "execution_plan_id", "action_id"):
            _validate_text(name, getattr(self, name))
        if not isinstance(self.action_snapshot, ExecutionAction):
            raise ValueError("action_snapshot must be an ExecutionAction")
        if self.action_snapshot.action_id != self.action_id:
            raise ValueError("action_snapshot must correspond to action_id")
        if not isinstance(self.approved_by, ApprovalActor):
            raise ValueError("approved_by must be an ApprovalActor")
        _validate_timestamp("approved_at_monotonic", self.approved_at_monotonic)
        _validate_expiration(
            self.approved_at_monotonic,
            self.expires_at_monotonic,
            "approved_at_monotonic",
        )
        for name in ("single_use", "used"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        object.__setattr__(self, "action_snapshot", deepcopy(self.action_snapshot))
        object.__setattr__(self, "approved_by", deepcopy(self.approved_by))
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class ApprovalResult:
    success: bool = False
    request: ActionApprovalRequest | None = None
    decision: ApprovalDecision | None = None
    grant: ApprovedActionGrant | None = None
    reasoning: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise ValueError("success must be a boolean")
        expected_types = (
            ("request", self.request, ActionApprovalRequest),
            ("decision", self.decision, ApprovalDecision),
            ("grant", self.grant, ApprovedActionGrant),
        )
        for name, value, expected in expected_types:
            if value is not None and not isinstance(value, expected):
                raise ValueError(f"{name} must be a {expected.__name__}")
        if self.success and self.request is None and self.decision is None and self.grant is None:
            raise ValueError("success=True requires a coherent approval result")
        if self.grant is not None:
            if self.decision is None or self.decision.status != ApprovalStatus.APPROVED:
                raise ValueError("grant requires an APPROVED decision")
        identifiers = {
            item.approval_id
            for item in (self.request, self.decision, self.grant)
            if item is not None
        }
        if len(identifiers) > 1:
            raise ValueError("approval_id must be consistent across approval result")
        object.__setattr__(self, "request", deepcopy(self.request))
        object.__setattr__(self, "decision", deepcopy(self.decision))
        object.__setattr__(self, "grant", deepcopy(self.grant))
        object.__setattr__(self, "reasoning", tuple(deepcopy(self.reasoning)))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


def _validate_text(name: str, value: str | None) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")


def _validate_enum(name: str, value: object, enum_type: type[StrEnum]) -> None:
    if not isinstance(value, enum_type):
        raise ValueError(f"{name} must be a {enum_type.__name__}")


def _validate_timestamp(name: str, value: float) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number")


def _validate_expiration(start: float, expires: float | None, start_name: str) -> None:
    if expires is None:
        return
    _validate_timestamp("expires_at_monotonic", expires)
    if expires < start:
        raise ValueError(f"expires_at_monotonic must not be earlier than {start_name}")


def _copy_safe_metadata(metadata: dict[str, object]) -> dict[str, object]:
    copied = deepcopy(dict(metadata))
    if _contains_secret(copied):
        raise ValueError("metadata must not contain passwords, tokens, secrets, or credentials")
    return copied


def _contains_secret(value: object, key: str = "") -> bool:
    sensitive = ("password", "senha", "token", "secret", "segredo", "credential", "credencial")
    normalized_key = key.strip().lower()
    if any(term in normalized_key for term in sensitive):
        return True
    if isinstance(value, dict):
        return any(_contains_secret(item, str(item_key)) for item_key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_secret(item) for item in value)
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        return any(term in normalized_value for term in sensitive)
    return False
