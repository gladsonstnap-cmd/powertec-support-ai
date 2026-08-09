"""Immutable contracts for a future allowlisted local executor.

The models in this module describe structure only. They do not execute, discover,
open, read, write, connect, spawn, cancel, or roll back anything.
"""

from copy import deepcopy
from dataclasses import dataclass, field, fields
from enum import StrEnum

from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget


class LocalOperationType(StrEnum):
    READ_ONLY = "READ_ONLY"
    STATE_CHANGING = "STATE_CHANGING"
    DESTRUCTIVE = "DESTRUCTIVE"


class LocalAdapterType(StrEnum):
    WINDOWS_SERVICE = "WINDOWS_SERVICE"
    WINDOWS_EVENT_LOG = "WINDOWS_EVENT_LOG"
    SYSTEM_INFORMATION = "SYSTEM_INFORMATION"
    PROCESS = "PROCESS"
    NETWORK_DIAGNOSTIC = "NETWORK_DIAGNOSTIC"
    DISK_INFORMATION = "DISK_INFORMATION"
    FILE_INFORMATION = "FILE_INFORMATION"
    UNKNOWN = "UNKNOWN"


class LocalExecutionState(StrEnum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    BLOCKED = "BLOCKED"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class OutputStreamType(StrEnum):
    STDOUT = "STDOUT"
    STDERR = "STDERR"
    SYSTEM = "SYSTEM"
    AUDIT = "AUDIT"


class RedactionReason(StrEnum):
    PASSWORD = "PASSWORD"
    TOKEN = "TOKEN"
    SECRET = "SECRET"
    CREDENTIAL = "CREDENTIAL"
    API_KEY = "API_KEY"
    AUTHORIZATION = "AUTHORIZATION"
    COOKIE = "COOKIE"
    PRIVATE_KEY = "PRIVATE_KEY"
    PERSONAL_DATA = "PERSONAL_DATA"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class LocalOperationArgument:
    name: str
    value: object = field(repr=False, hash=False)
    required: bool = False
    sensitive: bool = False
    description: str | None = None
    metadata: dict[str, object] = field(default_factory=dict, repr=False, hash=False)

    def __post_init__(self) -> None:
        _validate_text("name", self.name)
        _validate_flags(self, ("required", "sensitive"))
        if self.description is not None:
            _validate_text("description", self.description)
        object.__setattr__(self, "value", deepcopy(self.value))
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class AllowedLocalOperation:
    operation_name: str
    adapter_type: LocalAdapterType
    operation_type: LocalOperationType
    allowed_targets: tuple[ExecutionTarget, ...]
    allowed_risks: tuple[ExecutionRisk, ...]
    argument_names: tuple[str, ...]
    required_argument_names: tuple[str, ...]
    default_timeout_seconds: int
    max_timeout_seconds: int
    requires_grant: bool
    requires_confirmation: bool
    requires_human: bool
    supports_dry_run: bool
    supports_cancellation: bool
    supports_rollback: bool
    description: str
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _validate_text("operation_name", self.operation_name)
        _validate_text("description", self.description)
        _validate_enum("adapter_type", self.adapter_type, LocalAdapterType)
        _validate_enum("operation_type", self.operation_type, LocalOperationType)
        targets = _validated_unique_enums("allowed_targets", self.allowed_targets, ExecutionTarget)
        risks = _validated_unique_enums("allowed_risks", self.allowed_risks, ExecutionRisk)
        argument_names = _validated_unique_names("argument_names", self.argument_names)
        required_names = _validated_unique_names("required_argument_names", self.required_argument_names)
        if any(name not in argument_names for name in required_names):
            raise ValueError("required_argument_names must exist in argument_names")
        _validate_positive_integer("default_timeout_seconds", self.default_timeout_seconds)
        _validate_positive_integer("max_timeout_seconds", self.max_timeout_seconds)
        if self.default_timeout_seconds > self.max_timeout_seconds:
            raise ValueError("default_timeout_seconds must not exceed max_timeout_seconds")
        _validate_flags(
            self,
            (
                "requires_grant", "requires_confirmation", "requires_human",
                "supports_dry_run", "supports_cancellation", "supports_rollback",
            ),
        )
        object.__setattr__(self, "allowed_targets", targets)
        object.__setattr__(self, "allowed_risks", risks)
        object.__setattr__(self, "argument_names", argument_names)
        object.__setattr__(self, "required_argument_names", required_names)
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class LocalSandboxPolicy:
    allow_shell: bool = False
    allow_arbitrary_command: bool = False
    allow_environment_inheritance: bool = False
    allow_network_access: bool = False
    allow_filesystem_write: bool = False
    allow_registry_write: bool = False
    allow_service_state_change: bool = False
    allow_process_termination: bool = False
    allow_elevation: bool = False
    allow_child_processes: bool = False
    max_output_bytes: int = 1048576
    max_stderr_bytes: int = 262144
    max_runtime_seconds: int = 60
    preserve_raw_output: bool = False
    redact_sensitive_output: bool = True

    def __post_init__(self) -> None:
        limits = {"max_output_bytes", "max_stderr_bytes", "max_runtime_seconds"}
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name in limits:
                _validate_positive_integer(item.name, value)
            elif not isinstance(value, bool):
                raise ValueError(f"{item.name} must be a boolean")


@dataclass(frozen=True)
class LocalExecutionCommand:
    command_id: str
    operation_name: str
    adapter_type: LocalAdapterType
    arguments: tuple[LocalOperationArgument, ...]
    target: ExecutionTarget
    risk: ExecutionRisk
    operation_type: LocalOperationType
    timeout_seconds: int
    dry_run: bool
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _validate_text("command_id", self.command_id)
        _validate_text("operation_name", self.operation_name)
        _validate_enum("adapter_type", self.adapter_type, LocalAdapterType)
        _validate_enum("target", self.target, ExecutionTarget)
        _validate_enum("risk", self.risk, ExecutionRisk)
        _validate_enum("operation_type", self.operation_type, LocalOperationType)
        arguments = tuple(deepcopy(self.arguments))
        if any(not isinstance(item, LocalOperationArgument) for item in arguments):
            raise ValueError("arguments must contain LocalOperationArgument values")
        names = tuple(item.name for item in arguments)
        if len(set(names)) != len(names):
            raise ValueError("arguments must have unique names")
        _validate_positive_integer("timeout_seconds", self.timeout_seconds)
        if not isinstance(self.dry_run, bool):
            raise ValueError("dry_run must be a boolean")
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class LocalOutputChunk:
    sequence: int
    stream: OutputStreamType
    content: str
    truncated: bool
    redacted: bool
    redaction_reasons: tuple[RedactionReason, ...]
    occurred_at_monotonic: float
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _validate_non_negative_integer("sequence", self.sequence)
        _validate_enum("stream", self.stream, OutputStreamType)
        if not isinstance(self.content, str):
            raise ValueError("content must be a string")
        _validate_flags(self, ("truncated", "redacted"))
        reasons = _validated_unique_enums("redaction_reasons", self.redaction_reasons, RedactionReason)
        _validate_timestamp("occurred_at_monotonic", self.occurred_at_monotonic)
        object.__setattr__(self, "redaction_reasons", reasons)
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class LocalRawExecutionResult:
    command_id: str
    state: LocalExecutionState
    started_at_monotonic: float | None
    finished_at_monotonic: float | None
    exit_code: int | None
    stdout: str
    stderr: str
    output_chunks: tuple[LocalOutputChunk, ...]
    timed_out: bool
    cancelled: bool
    metadata: dict[str, object] = field(default_factory=dict, hash=False)
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_text("command_id", self.command_id)
        _validate_enum("state", self.state, LocalExecutionState)
        for name in ("started_at_monotonic", "finished_at_monotonic"):
            if getattr(self, name) is not None:
                _validate_timestamp(name, getattr(self, name))
        if (
            self.started_at_monotonic is not None
            and self.finished_at_monotonic is not None
            and self.finished_at_monotonic < self.started_at_monotonic
        ):
            raise ValueError("finished_at_monotonic must not be earlier than started_at_monotonic")
        if self.exit_code is not None and (not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool)):
            raise ValueError("exit_code must be an integer or None")
        if self.state == LocalExecutionState.SUCCESS and self.exit_code not in (None, 0):
            raise ValueError("SUCCESS requires exit_code zero or None")
        _validate_flags(self, ("timed_out", "cancelled"))
        if self.state == LocalExecutionState.TIMED_OUT and not self.timed_out:
            raise ValueError("TIMED_OUT state requires timed_out=True")
        if self.state == LocalExecutionState.CANCELLED and not self.cancelled:
            raise ValueError("CANCELLED state requires cancelled=True")
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise ValueError("stdout and stderr must be strings")
        chunks = tuple(deepcopy(self.output_chunks))
        if any(not isinstance(item, LocalOutputChunk) for item in chunks):
            raise ValueError("output_chunks must contain LocalOutputChunk values")
        sequences = tuple(item.sequence for item in chunks)
        if len(set(sequences)) != len(sequences):
            raise ValueError("output_chunks must have unique sequence values")
        object.__setattr__(self, "output_chunks", tuple(sorted(chunks, key=lambda item: item.sequence)))
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))


@dataclass(frozen=True)
class RedactedValue:
    placeholder: str
    reason: RedactionReason
    original_length: int | None = None
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _validate_text("placeholder", self.placeholder)
        _validate_enum("reason", self.reason, RedactionReason)
        if self.original_length is not None:
            _validate_non_negative_integer("original_length", self.original_length)
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class LocalSanitizedResult:
    command_id: str
    state: LocalExecutionState
    exit_code: int | None
    stdout_summary: str
    stderr_summary: str
    redactions: tuple[RedactedValue, ...]
    truncated: bool
    output_bytes: int
    errors: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _validate_text("command_id", self.command_id)
        _validate_enum("state", self.state, LocalExecutionState)
        if self.exit_code is not None and (not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool)):
            raise ValueError("exit_code must be an integer or None")
        if not isinstance(self.stdout_summary, str) or not isinstance(self.stderr_summary, str):
            raise ValueError("stdout_summary and stderr_summary must be strings")
        redactions = tuple(deepcopy(self.redactions))
        if any(not isinstance(item, RedactedValue) for item in redactions):
            raise ValueError("redactions must contain RedactedValue values")
        if not isinstance(self.truncated, bool):
            raise ValueError("truncated must be a boolean")
        _validate_non_negative_integer("output_bytes", self.output_bytes)
        object.__setattr__(self, "redactions", redactions)
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class LocalExecutionContract:
    contract_id: str
    executor_request_id: str
    execution_plan_id: str
    action_id: str
    grant_id: str
    operation: AllowedLocalOperation
    command: LocalExecutionCommand
    sandbox_policy: LocalSandboxPolicy
    state: LocalExecutionState
    created_at_monotonic: float
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        for name in ("contract_id", "executor_request_id", "execution_plan_id", "action_id", "grant_id"):
            _validate_text(name, getattr(self, name))
        if not isinstance(self.operation, AllowedLocalOperation):
            raise ValueError("operation must be an AllowedLocalOperation")
        if not isinstance(self.command, LocalExecutionCommand):
            raise ValueError("command must be a LocalExecutionCommand")
        if not isinstance(self.sandbox_policy, LocalSandboxPolicy):
            raise ValueError("sandbox_policy must be a LocalSandboxPolicy")
        _validate_enum("state", self.state, LocalExecutionState)
        if self.state in {LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS}:
            raise ValueError("initial contract state must not be RUNNING or SUCCESS")
        if self.operation.operation_name != self.command.operation_name:
            raise ValueError("operation_name must match between operation and command")
        if self.operation.adapter_type != self.command.adapter_type:
            raise ValueError("adapter_type must match between operation and command")
        if self.operation.operation_type != self.command.operation_type:
            raise ValueError("operation_type must match between operation and command")
        if self.command.target not in self.operation.allowed_targets:
            raise ValueError("command target is not allowed by operation")
        if self.command.risk not in self.operation.allowed_risks:
            raise ValueError("command risk is not allowed by operation")
        if self.command.timeout_seconds > self.operation.max_timeout_seconds:
            raise ValueError("command timeout exceeds operation maximum")
        if self.command.timeout_seconds > self.sandbox_policy.max_runtime_seconds:
            raise ValueError("command timeout exceeds sandbox maximum")
        names = tuple(item.name for item in self.command.arguments)
        if any(name not in self.operation.argument_names for name in names):
            raise ValueError("command contains an argument not allowed by operation")
        if any(name not in names for name in self.operation.required_argument_names):
            raise ValueError("command is missing a required operation argument")
        if self.command.dry_run and not self.operation.supports_dry_run:
            raise ValueError("operation does not support dry-run contracts")
        _validate_timestamp("created_at_monotonic", self.created_at_monotonic)
        object.__setattr__(self, "operation", deepcopy(self.operation))
        object.__setattr__(self, "command", deepcopy(self.command))
        object.__setattr__(self, "sandbox_policy", deepcopy(self.sandbox_policy))
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


def _validate_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")


def _validate_enum(name: str, value: object, enum_type: type[StrEnum]) -> None:
    if not isinstance(value, enum_type):
        raise ValueError(f"{name} must be a {enum_type.__name__}")


def _validate_flags(instance: object, names: tuple[str, ...]) -> None:
    for name in names:
        if not isinstance(getattr(instance, name), bool):
            raise ValueError(f"{name} must be a boolean")


def _validate_positive_integer(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_non_negative_integer(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _validate_timestamp(name: str, value: object) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")


def _validated_unique_names(name: str, values: object) -> tuple[str, ...]:
    copied = tuple(deepcopy(values))
    for value in copied:
        _validate_text(name, value)
    if len(set(copied)) != len(copied):
        raise ValueError(f"{name} must contain unique values")
    return copied


def _validated_unique_enums(name: str, values: object, enum_type: type[StrEnum]) -> tuple:
    copied = tuple(deepcopy(values))
    if any(not isinstance(value, enum_type) for value in copied):
        raise ValueError(f"{name} must contain {enum_type.__name__} values")
    if len(set(copied)) != len(copied):
        raise ValueError(f"{name} must contain unique values")
    return copied


def _copy_safe_metadata(metadata: dict[str, object]) -> dict[str, object]:
    copied = deepcopy(dict(metadata))
    if _contains_sensitive_data(copied):
        raise ValueError("metadata must not contain sensitive authorization data")
    return copied


def _contains_sensitive_data(value: object, key: str = "") -> bool:
    sensitive = (
        "password", "senha", "token", "secret", "segredo", "credential", "credencial",
        "api_key", "authorization", "bearer", "cookie", "private_key",
    )
    normalized_key = key.strip().lower()
    if any(term in normalized_key for term in sensitive):
        return True
    if isinstance(value, dict):
        return any(_contains_sensitive_data(item, str(item_key)) for item_key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_sensitive_data(item) for item in value)
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        return any(term in normalized_value for term in sensitive)
    return False
