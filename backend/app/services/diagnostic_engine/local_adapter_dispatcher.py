"""Immutable fail-closed routing for the closed set of local adapters."""

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_disk_information_adapter import LocalDiskInformationAdapter
from app.services.diagnostic_engine.local_event_log_adapter import LocalEventLogAdapter
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType,
    LocalExecutionContract,
    LocalExecutionState,
    LocalOperationType,
    LocalRawExecutionResult,
    LocalSanitizedResult,
)
from app.services.diagnostic_engine.local_executor_policy import DiagnosticLocalExecutorPolicy
from app.services.diagnostic_engine.local_system_information_adapter import LocalSystemInformationAdapter
from app.services.diagnostic_engine.local_windows_service_adapter import LocalWindowsServiceAdapter
from app.services.diagnostic_engine.local_process_adapter import LocalProcessAdapter


@dataclass(frozen=True)
class LocalAdapterDispatchResult:
    """Immutable snapshot produced at the local-adapter routing boundary."""

    success: bool = False
    contract: LocalExecutionContract | None = None
    raw_result: LocalRawExecutionResult | None = None
    sanitized_result: LocalSanitizedResult | None = None
    adapter_name: str | None = None
    reasoning: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise ValueError("success must be a boolean")
        expected = (
            ("contract", self.contract, LocalExecutionContract),
            ("raw_result", self.raw_result, LocalRawExecutionResult),
            ("sanitized_result", self.sanitized_result, LocalSanitizedResult),
        )
        for name, value, model_type in expected:
            if value is not None and not isinstance(value, model_type):
                raise ValueError(f"{name} must be a {model_type.__name__}")
        if self.success and (
            self.contract is None or self.raw_result is None or self.sanitized_result is None
        ):
            raise ValueError("success=True requires contract, raw_result, and sanitized_result")
        if self.adapter_name is not None and (
            not isinstance(self.adapter_name, str) or not self.adapter_name.strip()
        ):
            raise ValueError("adapter_name must be non-empty or None")
        if self.contract is not None:
            command_id = self.contract.command.command_id
            if self.raw_result is not None and self.raw_result.command_id != command_id:
                raise ValueError("raw_result command_id must match contract")
            if self.sanitized_result is not None and self.sanitized_result.command_id != command_id:
                raise ValueError("sanitized_result command_id must match contract")
        object.__setattr__(self, "contract", deepcopy(self.contract))
        object.__setattr__(self, "raw_result", deepcopy(self.raw_result))
        object.__setattr__(self, "sanitized_result", deepcopy(self.sanitized_result))
        object.__setattr__(self, "reasoning", tuple(deepcopy(self.reasoning)))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))
        object.__setattr__(self, "metadata", _copy_safe_metadata(self.metadata))


@dataclass(frozen=True)
class LocalAdapterDispatcher:
    """Resolve, execute, and sanitize only explicitly registered operations."""

    system_information_adapter: LocalSystemInformationAdapter = field(
        default_factory=LocalSystemInformationAdapter
    )
    disk_information_adapter: LocalDiskInformationAdapter = field(
        default_factory=LocalDiskInformationAdapter
    )
    policy: DiagnosticLocalExecutorPolicy = field(default_factory=DiagnosticLocalExecutorPolicy)
    event_log_adapter: LocalEventLogAdapter = field(default_factory=LocalEventLogAdapter)
    windows_service_adapter: LocalWindowsServiceAdapter = field(
        default_factory=LocalWindowsServiceAdapter
    )
    process_adapter: LocalProcessAdapter = field(default_factory=LocalProcessAdapter)
    _registry: Mapping[str, object] = field(init=False, repr=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.system_information_adapter, LocalSystemInformationAdapter):
            raise ValueError("system_information_adapter must be a LocalSystemInformationAdapter")
        if not isinstance(self.disk_information_adapter, LocalDiskInformationAdapter):
            raise ValueError("disk_information_adapter must be a LocalDiskInformationAdapter")
        if not isinstance(self.policy, DiagnosticLocalExecutorPolicy):
            raise ValueError("policy must be a DiagnosticLocalExecutorPolicy")
        if not isinstance(self.event_log_adapter, LocalEventLogAdapter):
            raise ValueError("event_log_adapter must be a LocalEventLogAdapter")
        if not isinstance(self.windows_service_adapter, LocalWindowsServiceAdapter):
            raise ValueError("windows_service_adapter must be a LocalWindowsServiceAdapter")
        if not isinstance(self.process_adapter, LocalProcessAdapter):
            raise ValueError("process_adapter must be a LocalProcessAdapter")
        registry = {
            "check_disk_information": self.disk_information_adapter,
            "check_disk_space": self.disk_information_adapter,
            "check_service_status": self.windows_service_adapter,
            "collect_event_logs": self.event_log_adapter,
            "list_processes": self.process_adapter,
            "list_windows_services": self.windows_service_adapter,
            "read_system_information": self.system_information_adapter,
            "read_system_process_information": self.process_adapter,
        }
        object.__setattr__(self, "_registry", MappingProxyType(registry))

    def supported_operations(self) -> tuple[str, ...]:
        return tuple(sorted(self._registry))

    def contains(self, operation_name: str) -> bool:
        return isinstance(operation_name, str) and operation_name in self._registry

    def resolve(self, operation_name: str) -> object | None:
        if not isinstance(operation_name, str):
            return None
        return self._registry.get(operation_name)

    def dispatch(
        self,
        contract: LocalExecutionContract,
        now_monotonic: float,
    ) -> LocalAdapterDispatchResult:
        error = self._contract_error(contract, now_monotonic)
        if error is not None:
            return self._failure(error, contract if isinstance(contract, LocalExecutionContract) else None)
        operation_name = contract.command.operation_name
        adapter = self.resolve(operation_name)
        if adapter is None:
            return self._failure("Operação local não registrada.", contract)
        adapter_name = type(adapter).__name__
        try:
            raw_result = adapter.execute(contract, now_monotonic)
            if not isinstance(raw_result, LocalRawExecutionResult):
                return self._failure("Falha no adapter local.", contract, adapter_name=adapter_name)
            if raw_result.command_id != contract.command.command_id:
                return self._failure("Resultado local incompatível com o contrato.", contract, adapter_name=adapter_name)
        except Exception:
            return self._failure("Falha no adapter local.", contract, adapter_name=adapter_name)
        try:
            sanitized_result = adapter.sanitize(raw_result)
            if not isinstance(sanitized_result, LocalSanitizedResult):
                return self._failure(
                    "Falha no adapter local.", contract, raw_result, adapter_name
                )
            if sanitized_result.command_id != contract.command.command_id:
                return self._failure(
                    "Resultado sanitizado incompatível com o contrato.",
                    contract,
                    raw_result,
                    adapter_name,
                )
        except Exception:
            return self._failure("Falha no adapter local.", contract, raw_result, adapter_name)
        if raw_result.state != LocalExecutionState.SUCCESS:
            return LocalAdapterDispatchResult(
                success=False,
                contract=contract,
                raw_result=raw_result,
                sanitized_result=sanitized_result,
                adapter_name=adapter_name,
                reasoning=("O adapter registrado foi executado e sanitizado.",),
                errors=("O adapter local retornou falha.",),
                metadata={"operation_name": operation_name},
            )
        return LocalAdapterDispatchResult(
            success=True,
            contract=contract,
            raw_result=raw_result,
            sanitized_result=sanitized_result,
            adapter_name=adapter_name,
            reasoning=(
                f"Operação {operation_name} resolvida pelo registry local fechado.",
                "O resultado bruto foi sanitizado pelo mesmo adapter.",
            ),
            metadata={"operation_name": operation_name},
        )

    def _contract_error(self, contract: object, now_monotonic: object) -> str | None:
        if not isinstance(contract, LocalExecutionContract):
            return "Contrato local inválido."
        if not isinstance(now_monotonic, int | float) or isinstance(now_monotonic, bool) or now_monotonic < 0:
            return "Momento monotônico inválido."
        operation = contract.operation
        command = contract.command
        expected_adapter = {
            "read_system_information": LocalAdapterType.SYSTEM_INFORMATION,
            "check_disk_information": LocalAdapterType.DISK_INFORMATION,
            "check_disk_space": LocalAdapterType.DISK_INFORMATION,
            "collect_event_logs": LocalAdapterType.WINDOWS_EVENT_LOG,
            "list_windows_services": LocalAdapterType.WINDOWS_SERVICE,
            "check_service_status": LocalAdapterType.WINDOWS_SERVICE,
            "list_processes": LocalAdapterType.PROCESS,
            "read_system_process_information": LocalAdapterType.PROCESS,
        }.get(command.operation_name)
        if expected_adapter is None or not self.contains(command.operation_name):
            return "Operação local não registrada."
        if operation.operation_name != command.operation_name:
            return "Operação do contrato e comando são incompatíveis."
        if operation.adapter_type != expected_adapter or command.adapter_type != expected_adapter:
            return "Adapter local incompatível."
        if operation.operation_type != LocalOperationType.READ_ONLY or command.operation_type != LocalOperationType.READ_ONLY:
            return "Tipo de operação incompatível."
        if command.target != ExecutionTarget.WINDOWS or ExecutionTarget.WINDOWS not in operation.allowed_targets:
            return "Target local incompatível."
        if command.risk != ExecutionRisk.LOW or ExecutionRisk.LOW not in operation.allowed_risks:
            return "Risco local incompatível."
        if contract.state not in {LocalExecutionState.PENDING, LocalExecutionState.VALIDATED, LocalExecutionState.READY}:
            return "Estado do contrato incompatível."
        if (
            not isinstance(command.timeout_seconds, int)
            or isinstance(command.timeout_seconds, bool)
            or command.timeout_seconds <= 0
            or command.timeout_seconds > operation.max_timeout_seconds
            or command.timeout_seconds > contract.sandbox_policy.max_runtime_seconds
        ):
            return "Timeout estrutural inválido."
        sandbox = contract.sandbox_policy
        if any(
            (
                sandbox.allow_shell,
                sandbox.allow_arbitrary_command,
                sandbox.allow_environment_inheritance,
                sandbox.allow_network_access,
                sandbox.allow_filesystem_write,
                sandbox.allow_registry_write,
                sandbox.allow_service_state_change,
                sandbox.allow_process_termination,
                sandbox.allow_elevation,
                sandbox.allow_child_processes,
            )
        ):
            return "Sandbox incompatível com dispatch read-only."
        try:
            policy_allowed = (
                self.policy.is_adapter_allowed(command.adapter_type)
                and self.policy.is_target_allowed(command.target)
                and self.policy.is_risk_allowed(command.risk)
                and self.policy.is_operation_type_allowed(command.operation_type)
                and self.policy.validate_timeout(command.timeout_seconds)
            )
        except Exception:
            return "Policy local inválida."
        if not policy_allowed:
            return "Policy local bloqueou o contrato."
        if not isinstance(command.dry_run, bool):
            return "Flag dry-run inválida."
        if command.dry_run:
            if not self.policy.allow_dry_run or not operation.supports_dry_run:
                return "Policy local bloqueou o dry-run."
        else:
            try:
                real_allowed = self.policy.can_execute_real_operation(
                    adapter_type=command.adapter_type,
                    target=command.target,
                    risk=command.risk,
                    operation_type=command.operation_type,
                )
            except Exception:
                return "Policy local inválida."
            if not real_allowed:
                return "Policy local bloqueou a execução real."
        return None

    @staticmethod
    def _failure(
        error: str,
        contract: LocalExecutionContract | None = None,
        raw_result: LocalRawExecutionResult | None = None,
        adapter_name: str | None = None,
    ) -> LocalAdapterDispatchResult:
        return LocalAdapterDispatchResult(
            success=False,
            contract=contract,
            raw_result=raw_result,
            adapter_name=adapter_name,
            reasoning=("Dispatch local bloqueado em modo fail-closed.",),
            errors=(error,),
        )


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
        return any(term in value.strip().lower() for term in sensitive)
    return False
