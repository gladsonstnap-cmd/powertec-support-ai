"""Immutable contracts and audit records for a future safe executor."""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum

from app.services.diagnostic_engine.approval_models import ApprovedActionGrant
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction,
    ExecutionParameter,
    ExecutionRisk,
    ExecutionTarget,
)


class ExecutorStatus(StrEnum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    AUTHORIZED = "AUTHORIZED"
    BLOCKED = "BLOCKED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLBACK_SUCCESS = "ROLLBACK_SUCCESS"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"


class ExecutorBlockReason(StrEnum):
    MISSING_GRANT = "MISSING_GRANT"
    INVALID_GRANT = "INVALID_GRANT"
    EXPIRED_GRANT = "EXPIRED_GRANT"
    USED_GRANT = "USED_GRANT"
    ACTION_MISMATCH = "ACTION_MISMATCH"
    PLAN_MISMATCH = "PLAN_MISMATCH"
    SESSION_MISMATCH = "SESSION_MISMATCH"
    RISK_BLOCKED = "RISK_BLOCKED"
    TARGET_BLOCKED = "TARGET_BLOCKED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    DESTRUCTIVE_ACTION = "DESTRUCTIVE_ACTION"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    INVALID_PARAMETERS = "INVALID_PARAMETERS"
    INVALID_STATE = "INVALID_STATE"
    UNKNOWN = "UNKNOWN"


class AuditEventType(StrEnum):
    EXECUTION_REQUESTED = "EXECUTION_REQUESTED"
    VALIDATION_STARTED = "VALIDATION_STARTED"
    VALIDATION_PASSED = "VALIDATION_PASSED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    AUTHORIZATION_CHECKED = "AUTHORIZATION_CHECKED"
    AUTHORIZATION_ACCEPTED = "AUTHORIZATION_ACCEPTED"
    AUTHORIZATION_REJECTED = "AUTHORIZATION_REJECTED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_SUCCEEDED = "EXECUTION_SUCCEEDED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_CANCELLED = "EXECUTION_CANCELLED"
    EXECUTION_TIMED_OUT = "EXECUTION_TIMED_OUT"
    GRANT_CONSUMED = "GRANT_CONSUMED"
    ROLLBACK_REQUESTED = "ROLLBACK_REQUESTED"
    ROLLBACK_STARTED = "ROLLBACK_STARTED"
    ROLLBACK_SUCCEEDED = "ROLLBACK_SUCCEEDED"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"


@dataclass(frozen=True)
class ExecutionContext:
    session_id: str
    diagnostic_plan_id: str | None
    execution_plan_id: str
    action_id: str
    grant_id: str
    approval_id: str
    target: ExecutionTarget
    risk: ExecutionRisk
    requested_at_monotonic: float
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        for name in ("session_id", "execution_plan_id", "action_id", "grant_id", "approval_id"):
            _validate_text(name, getattr(self, name))
        if self.diagnostic_plan_id is not None:
            _validate_text("diagnostic_plan_id", self.diagnostic_plan_id)
        _validate_enum("target", self.target, ExecutionTarget)
        _validate_enum("risk", self.risk, ExecutionRisk)
        _validate_timestamp("requested_at_monotonic", self.requested_at_monotonic)
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class ExecutorRequest:
    request_id: str
    context: ExecutionContext
    action_snapshot: ExecutionAction
    grant_snapshot: ApprovedActionGrant
    status: ExecutorStatus = ExecutorStatus.PENDING
    timeout_seconds: int = 30
    dry_run: bool = True
    metadata: dict[str, object] = field(default_factory=dict, hash=False)
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_text("request_id", self.request_id)
        if not isinstance(self.context, ExecutionContext):
            raise ValueError("context must be an ExecutionContext")
        if not isinstance(self.action_snapshot, ExecutionAction):
            raise ValueError("action_snapshot must be an ExecutionAction")
        if not isinstance(self.grant_snapshot, ApprovedActionGrant):
            raise ValueError("grant_snapshot must be an ApprovedActionGrant")
        _validate_enum("status", self.status, ExecutorStatus)
        if self.status == ExecutorStatus.SUCCESS:
            raise ValueError("initial status must not be SUCCESS")
        if not isinstance(self.timeout_seconds, int) or isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive integer")
        if not isinstance(self.dry_run, bool):
            raise ValueError("dry_run must be a boolean")
        if self.action_snapshot.action_id != self.context.action_id:
            raise ValueError("action_snapshot.action_id must match context.action_id")
        if self.action_snapshot.target != self.context.target:
            raise ValueError("action_snapshot.target must match context.target")
        if self.action_snapshot.risk != self.context.risk:
            raise ValueError("action_snapshot.risk must match context.risk")
        correlations = (
            ("action_id", self.grant_snapshot.action_id, self.context.action_id),
            ("grant_id", self.grant_snapshot.grant_id, self.context.grant_id),
            ("approval_id", self.grant_snapshot.approval_id, self.context.approval_id),
            ("execution_plan_id", self.grant_snapshot.execution_plan_id, self.context.execution_plan_id),
        )
        for name, actual, expected in correlations:
            if actual != expected:
                raise ValueError(f"grant_snapshot.{name} must match context.{name}")
        if self.grant_snapshot.action_snapshot != self.action_snapshot:
            raise ValueError("grant_snapshot action must match action_snapshot")
        object.__setattr__(self, "context", deepcopy(self.context))
        object.__setattr__(self, "action_snapshot", deepcopy(self.action_snapshot))
        object.__setattr__(self, "grant_snapshot", deepcopy(self.grant_snapshot))
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    event_type: AuditEventType
    request_id: str
    session_id: str
    execution_plan_id: str
    action_id: str
    occurred_at_monotonic: float
    message: str
    metadata: dict[str, object] = field(default_factory=dict, hash=False)
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("event_id", "request_id", "session_id", "execution_plan_id", "action_id", "message"):
            _validate_text(name, getattr(self, name))
        _validate_enum("event_type", self.event_type, AuditEventType)
        _validate_timestamp("occurred_at_monotonic", self.occurred_at_monotonic)
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))


@dataclass(frozen=True)
class ExecutionAttempt:
    attempt_id: str
    request_id: str
    attempt_number: int
    status: ExecutorStatus = ExecutorStatus.PENDING
    started_at_monotonic: float | None = None
    finished_at_monotonic: float | None = None
    exit_code: int | None = None
    output_summary: str | None = None
    error_summary: str | None = None
    block_reason: ExecutorBlockReason | None = None
    audit_events: tuple[AuditEvent, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _validate_text("attempt_id", self.attempt_id)
        _validate_text("request_id", self.request_id)
        if not isinstance(self.attempt_number, int) or isinstance(self.attempt_number, bool) or self.attempt_number <= 0:
            raise ValueError("attempt_number must be a positive integer")
        _validate_enum("status", self.status, ExecutorStatus)
        for name in ("started_at_monotonic", "finished_at_monotonic"):
            value = getattr(self, name)
            if value is not None:
                _validate_timestamp(name, value)
        if (
            self.started_at_monotonic is not None
            and self.finished_at_monotonic is not None
            and self.finished_at_monotonic < self.started_at_monotonic
        ):
            raise ValueError("finished_at_monotonic must not be earlier than started_at_monotonic")
        if self.exit_code is not None and (not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool)):
            raise ValueError("exit_code must be an integer or None")
        if self.block_reason is not None:
            _validate_enum("block_reason", self.block_reason, ExecutorBlockReason)
        if self.status == ExecutorStatus.BLOCKED and self.block_reason is None:
            raise ValueError("BLOCKED status requires block_reason")
        if self.status == ExecutorStatus.SUCCESS and self.block_reason is not None:
            raise ValueError("SUCCESS status must not have block_reason")
        events = tuple(deepcopy(self.audit_events))
        if any(not isinstance(item, AuditEvent) for item in events):
            raise ValueError("audit_events must contain AuditEvent values")
        object.__setattr__(self, "audit_events", events)
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class RollbackPlan:
    rollback_id: str
    original_action_id: str
    supported: bool
    description: str | None = None
    rollback_action_name: str | None = None
    parameters: tuple[ExecutionParameter, ...] = ()
    requires_confirmation: bool = False
    requires_human: bool = False
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _validate_text("rollback_id", self.rollback_id)
        _validate_text("original_action_id", self.original_action_id)
        for name in ("supported", "requires_confirmation", "requires_human"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        if self.supported:
            _validate_text("description", self.description)
        if self.rollback_action_name is not None:
            _validate_text("rollback_action_name", self.rollback_action_name)
        parameters = tuple(deepcopy(self.parameters))
        if any(not isinstance(item, ExecutionParameter) for item in parameters):
            raise ValueError("parameters must contain ExecutionParameter values")
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class ExecutorResult:
    success: bool = False
    request: ExecutorRequest | None = None
    attempt: ExecutionAttempt | None = None
    rollback_plan: RollbackPlan | None = None
    audit_events: tuple[AuditEvent, ...] = ()
    reasoning: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise ValueError("success must be a boolean")
        expected = (
            ("request", self.request, ExecutorRequest),
            ("attempt", self.attempt, ExecutionAttempt),
            ("rollback_plan", self.rollback_plan, RollbackPlan),
        )
        for name, value, model_type in expected:
            if value is not None and not isinstance(value, model_type):
                raise ValueError(f"{name} must be a {model_type.__name__}")
        if self.success and (self.request is None or self.attempt is None):
            raise ValueError("success=True requires request and attempt")
        if self.success and self.attempt.status != ExecutorStatus.SUCCESS:
            raise ValueError("success=True requires attempt.status SUCCESS")
        if self.request is not None and self.attempt is not None and self.request.request_id != self.attempt.request_id:
            raise ValueError("request_id must be consistent between request and attempt")
        events = tuple(deepcopy(self.audit_events))
        if any(not isinstance(item, AuditEvent) for item in events):
            raise ValueError("audit_events must contain AuditEvent values")
        event_ids = tuple(item.event_id for item in events)
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("audit_events must have unique event_id values")
        object.__setattr__(self, "request", deepcopy(self.request))
        object.__setattr__(self, "attempt", deepcopy(self.attempt))
        object.__setattr__(self, "rollback_plan", deepcopy(self.rollback_plan))
        object.__setattr__(self, "audit_events", events)
        object.__setattr__(self, "reasoning", tuple(deepcopy(self.reasoning)))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class ExecutionAuditTrail:
    session_id: str
    execution_plan_id: str
    events: tuple[AuditEvent, ...] = ()
    attempts: tuple[ExecutionAttempt, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _validate_text("session_id", self.session_id)
        _validate_text("execution_plan_id", self.execution_plan_id)
        events = tuple(deepcopy(self.events))
        attempts = tuple(deepcopy(self.attempts))
        if any(not isinstance(item, AuditEvent) for item in events):
            raise ValueError("events must contain AuditEvent values")
        if any(not isinstance(item, ExecutionAttempt) for item in attempts):
            raise ValueError("attempts must contain ExecutionAttempt values")
        event_ids = tuple(item.event_id for item in events)
        attempt_ids = tuple(item.attempt_id for item in attempts)
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("events must have unique event_id values")
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError("attempts must have unique attempt_id values")
        if any(item.session_id != self.session_id for item in events):
            raise ValueError("events must match session_id")
        if any(item.execution_plan_id != self.execution_plan_id for item in events):
            raise ValueError("events must match execution_plan_id")
        object.__setattr__(self, "events", tuple(sorted(events, key=lambda item: (item.occurred_at_monotonic, item.event_id))))
        object.__setattr__(self, "attempts", tuple(sorted(attempts, key=lambda item: (item.attempt_number, item.attempt_id))))
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


def _validate_text(name: str, value: str | None) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")


def _validate_enum(name: str, value: object, enum_type: type[StrEnum]) -> None:
    if not isinstance(value, enum_type):
        raise ValueError(f"{name} must be a {enum_type.__name__}")


def _validate_timestamp(name: str, value: object) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")


def _copy_safe_metadata(metadata: dict[str, object]) -> dict[str, object]:
    copied = deepcopy(dict(metadata))
    if _contains_secret(copied):
        raise ValueError("metadata must not contain passwords, tokens, secrets, credentials, or authorization data")
    return copied


def _contains_secret(value: object, key: str = "") -> bool:
    sensitive = (
        "password", "senha", "token", "secret", "segredo", "credential", "credencial",
        "api_key", "authorization", "bearer", "cookie", "private_key",
    )
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
