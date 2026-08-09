"""Closed structural allowlist for future safe local operations."""

from copy import deepcopy
from dataclasses import dataclass, field

from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    AllowedLocalOperation,
    LocalAdapterType,
    LocalExecutionCommand,
    LocalExecutionContract,
    LocalExecutionState,
    LocalOperationArgument,
    LocalOperationType,
    LocalSandboxPolicy,
)
from app.services.diagnostic_engine.local_executor_policy import DiagnosticLocalExecutorPolicy


def _operation(
    name: str,
    adapter: LocalAdapterType,
    target: ExecutionTarget,
    arguments: tuple[str, ...] = (),
    required: tuple[str, ...] = (),
    description: str = "Structured read-only operation; no operation is executed.",
) -> AllowedLocalOperation:
    return AllowedLocalOperation(
        operation_name=name,
        adapter_type=adapter,
        operation_type=LocalOperationType.READ_ONLY,
        allowed_targets=(target,),
        allowed_risks=(ExecutionRisk.LOW,),
        argument_names=arguments,
        required_argument_names=required,
        default_timeout_seconds=30,
        max_timeout_seconds=30,
        requires_grant=True,
        requires_confirmation=False,
        requires_human=False,
        supports_dry_run=True,
        supports_cancellation=True,
        supports_rollback=False,
        description=description,
    )


def _catalog_operations() -> tuple[AllowedLocalOperation, ...]:
    operations = (
        _operation(
            "read_system_information", LocalAdapterType.SYSTEM_INFORMATION, ExecutionTarget.WINDOWS,
            description="Read structured system information; no system query is executed.",
        ),
        _operation(
            "list_windows_services", LocalAdapterType.WINDOWS_SERVICE, ExecutionTarget.WINDOWS,
            ("name_filter",), description="List service information only; no service is changed.",
        ),
        _operation(
            "check_service_status", LocalAdapterType.WINDOWS_SERVICE, ExecutionTarget.WINDOWS,
            ("service_name",), ("service_name",), "Read one service status; no service is changed.",
        ),
        _operation(
            "collect_event_logs", LocalAdapterType.WINDOWS_EVENT_LOG, ExecutionTarget.WINDOWS,
            ("log_name", "hours"), ("log_name",), "Collect a structural log request; no log is read or deleted.",
        ),
        _operation(
            "list_processes", LocalAdapterType.PROCESS, ExecutionTarget.WINDOWS,
            ("name_filter",), description="List process information only; no process is terminated.",
        ),
        _operation(
            "read_system_process_information", LocalAdapterType.PROCESS, ExecutionTarget.WINDOWS,
            ("process_name",), ("process_name",), "Read structural process information; no process is accessed.",
        ),
        _operation(
            "check_disk_information", LocalAdapterType.DISK_INFORMATION, ExecutionTarget.WINDOWS,
            ("disk_name",), description="Read structural disk information; no disk is accessed.",
        ),
        _operation(
            "check_disk_space", LocalAdapterType.DISK_INFORMATION, ExecutionTarget.WINDOWS,
            ("drive",), description="Read a structural disk-space request; no disk is accessed.",
        ),
        _operation(
            "check_network_configuration", LocalAdapterType.NETWORK_DIAGNOSTIC, ExecutionTarget.NETWORK,
            description="Represent a network configuration check; no network call is made.",
        ),
        _operation(
            "ping_host", LocalAdapterType.NETWORK_DIAGNOSTIC, ExecutionTarget.NETWORK,
            ("host",), ("host",), "Represent a ping request; no ping or network call is made.",
        ),
        _operation(
            "check_port", LocalAdapterType.NETWORK_DIAGNOSTIC, ExecutionTarget.NETWORK,
            ("host", "port"), ("host", "port"), "Represent a port check; no socket is opened.",
        ),
        _operation(
            "validate_configuration", LocalAdapterType.SYSTEM_INFORMATION, ExecutionTarget.WINDOWS,
            ("configuration_name",), ("configuration_name",),
            "Validate a named structural configuration; no system query is made.",
        ),
    )
    ordered = tuple(sorted(operations, key=lambda item: item.operation_name))
    names = tuple(item.operation_name for item in ordered)
    if len(set(names)) != len(names):
        raise ValueError("catalog operation_name values must be unique")
    for item in ordered:
        if item.adapter_type == LocalAdapterType.UNKNOWN:
            raise ValueError("catalog must not contain UNKNOWN adapters")
        if ExecutionTarget.UNKNOWN in item.allowed_targets:
            raise ValueError("catalog must not contain UNKNOWN targets")
        if item.operation_type != LocalOperationType.READ_ONLY:
            raise ValueError("catalog supports READ_ONLY operations only")
        if item.allowed_risks != (ExecutionRisk.LOW,):
            raise ValueError("catalog supports LOW risk only")
    return ordered


@dataclass(frozen=True)
class SafeLocalOperationCatalog:
    """Immutable public view over a closed, deterministic operation tuple."""

    _operations: tuple[AllowedLocalOperation, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_operations", _catalog_operations())

    def list_operations(self) -> tuple[AllowedLocalOperation, ...]:
        return deepcopy(self._operations)

    def get(self, operation_name: str) -> AllowedLocalOperation | None:
        if not isinstance(operation_name, str):
            return None
        found = next((item for item in self._operations if item.operation_name == operation_name), None)
        return deepcopy(found)

    def require(self, operation_name: str) -> AllowedLocalOperation:
        found = self.get(operation_name)
        if found is None:
            raise ValueError(f"Unknown local operation: {operation_name!r}")
        return found

    def contains(self, operation_name: str) -> bool:
        return self.get(operation_name) is not None

    def names(self) -> tuple[str, ...]:
        return tuple(item.operation_name for item in self._operations)

    def find_by_adapter(self, adapter_type: LocalAdapterType) -> tuple[AllowedLocalOperation, ...]:
        self._require_enum("adapter_type", adapter_type, LocalAdapterType)
        return deepcopy(tuple(item for item in self._operations if item.adapter_type == adapter_type))

    def find_by_target(self, target: ExecutionTarget) -> tuple[AllowedLocalOperation, ...]:
        self._require_enum("target", target, ExecutionTarget)
        return deepcopy(tuple(item for item in self._operations if target in item.allowed_targets))

    def find_by_risk(self, risk: ExecutionRisk) -> tuple[AllowedLocalOperation, ...]:
        self._require_enum("risk", risk, ExecutionRisk)
        return deepcopy(tuple(item for item in self._operations if risk in item.allowed_risks))

    def find_by_operation_type(
        self, operation_type: LocalOperationType
    ) -> tuple[AllowedLocalOperation, ...]:
        self._require_enum("operation_type", operation_type, LocalOperationType)
        return deepcopy(tuple(item for item in self._operations if item.operation_type == operation_type))

    def is_allowed_by_policy(
        self, operation_name: str, policy: DiagnosticLocalExecutorPolicy
    ) -> bool:
        if not isinstance(policy, DiagnosticLocalExecutorPolicy):
            raise ValueError("policy must be a DiagnosticLocalExecutorPolicy")
        operation = self.get(operation_name)
        if operation is None:
            return False
        return (
            policy.is_adapter_allowed(operation.adapter_type)
            and all(policy.is_target_allowed(target) for target in operation.allowed_targets)
            and all(policy.is_risk_allowed(risk) for risk in operation.allowed_risks)
            and policy.is_operation_type_allowed(operation.operation_type)
            and policy.validate_timeout(operation.default_timeout_seconds)
        )

    def build_command(
        self,
        operation_name: str,
        *,
        command_id: str,
        arguments: tuple[LocalOperationArgument, ...] = (),
        dry_run: bool = True,
        timeout_seconds: int | None = None,
    ) -> LocalExecutionCommand:
        operation = self.require(operation_name)
        if not isinstance(arguments, tuple):
            raise ValueError("arguments must be a tuple")
        if any(not isinstance(item, LocalOperationArgument) for item in arguments):
            raise ValueError("arguments must contain LocalOperationArgument values")
        names = tuple(item.name for item in arguments)
        if len(set(names)) != len(names):
            raise ValueError("arguments must have unique names")
        if any(name not in operation.argument_names for name in names):
            raise ValueError("command contains an argument not allowed by the catalog")
        if any(name not in names for name in operation.required_argument_names):
            raise ValueError("command is missing a required catalog argument")
        timeout = operation.default_timeout_seconds if timeout_seconds is None else timeout_seconds
        if (
            not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or timeout <= 0
            or timeout > operation.max_timeout_seconds
        ):
            raise ValueError("timeout_seconds is outside the catalog operation limit")
        return LocalExecutionCommand(
            command_id=command_id,
            operation_name=operation.operation_name,
            adapter_type=operation.adapter_type,
            arguments=arguments,
            target=operation.allowed_targets[0],
            risk=operation.allowed_risks[0],
            operation_type=operation.operation_type,
            timeout_seconds=timeout,
            dry_run=dry_run,
        )

    def build_contract(
        self,
        *,
        contract_id: str,
        executor_request_id: str,
        execution_plan_id: str,
        action_id: str,
        grant_id: str,
        operation_name: str,
        command_id: str,
        arguments: tuple[LocalOperationArgument, ...] = (),
        dry_run: bool = True,
        timeout_seconds: int | None = None,
        sandbox_policy: LocalSandboxPolicy | None = None,
        created_at_monotonic: float = 0.0,
    ) -> LocalExecutionContract:
        operation = self.require(operation_name)
        command = self.build_command(
            operation_name,
            command_id=command_id,
            arguments=arguments,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
        )
        if sandbox_policy is not None and not isinstance(sandbox_policy, LocalSandboxPolicy):
            raise ValueError("sandbox_policy must be a LocalSandboxPolicy")
        return LocalExecutionContract(
            contract_id=contract_id,
            executor_request_id=executor_request_id,
            execution_plan_id=execution_plan_id,
            action_id=action_id,
            grant_id=grant_id,
            operation=operation,
            command=command,
            sandbox_policy=sandbox_policy if sandbox_policy is not None else LocalSandboxPolicy(),
            state=LocalExecutionState.PENDING,
            created_at_monotonic=created_at_monotonic,
        )

    @staticmethod
    def _require_enum(name: str, value: object, enum_type: type) -> None:
        if not isinstance(value, enum_type):
            raise ValueError(f"{name} must be a {enum_type.__name__}")
