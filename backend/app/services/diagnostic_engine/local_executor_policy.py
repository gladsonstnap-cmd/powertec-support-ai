"""Fail-closed configuration for a future safe local executor."""

from dataclasses import dataclass, fields

from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType,
    LocalOperationType,
    LocalSandboxPolicy,
)


@dataclass(frozen=True)
class DiagnosticLocalExecutorPolicy:
    """Immutable policy queries and limits; this class performs no execution."""

    max_arguments_per_command: int = 20
    max_argument_name_length: int = 128
    max_string_argument_length: int = 4096
    default_timeout_seconds: int = 30
    max_timeout_seconds: int = 60
    max_output_bytes: int = 1048576
    max_stdout_bytes: int = 786432
    max_stderr_bytes: int = 262144
    max_output_chunks: int = 1000
    max_output_chunk_bytes: int = 65536
    max_redactions: int = 100
    max_errors: int = 20
    max_metadata_depth: int = 8
    max_metadata_items: int = 100

    allow_local_execution: bool = False
    allow_real_execution: bool = False
    allow_dry_run: bool = True
    require_dry_run_before_real_execution: bool = True

    allow_windows_service_adapter: bool = False
    allow_windows_event_log_adapter: bool = True
    allow_system_information_adapter: bool = True
    allow_process_adapter: bool = True
    allow_network_diagnostic_adapter: bool = True
    allow_disk_information_adapter: bool = True
    allow_file_information_adapter: bool = False
    allow_unknown_adapter: bool = False

    allow_windows_target: bool = True
    allow_network_target: bool = True
    allow_linux_target: bool = False
    allow_remote_agent_target: bool = False
    allow_unknown_target: bool = False

    allow_low_risk: bool = True
    allow_medium_risk: bool = False
    allow_high_risk: bool = False
    allow_critical_risk: bool = False

    allow_read_only_operations: bool = True
    allow_state_changing_operations: bool = False
    allow_destructive_operations: bool = False

    allow_shell: bool = False
    allow_arbitrary_commands: bool = False
    allow_arbitrary_executables: bool = False
    allow_scripts: bool = False
    allow_command_interpolation: bool = False
    allow_shell_metacharacters: bool = False
    allow_environment_inheritance: bool = False
    allow_environment_override: bool = False

    allow_network_access: bool = False
    allow_outbound_connections: bool = False
    allow_inbound_connections: bool = False
    allow_dns_resolution: bool = False
    allow_arbitrary_host: bool = False
    allow_arbitrary_port: bool = False

    allow_filesystem_read: bool = False
    allow_filesystem_write: bool = False
    allow_filesystem_delete: bool = False
    allow_arbitrary_path: bool = False
    allow_path_traversal: bool = False

    allow_registry_read: bool = False
    allow_registry_write: bool = False
    allow_service_query: bool = False
    allow_service_state_change: bool = False
    allow_process_listing: bool = False
    allow_process_termination: bool = False
    allow_child_processes: bool = False
    allow_elevation: bool = False
    allow_system_shutdown: bool = False
    allow_system_restart: bool = False

    require_valid_grant: bool = True
    require_unexpired_grant: bool = True
    reject_used_grant: bool = True
    require_action_match: bool = True
    require_execution_plan_match: bool = True
    require_session_match: bool = True
    require_confirmation_for_state_change: bool = True
    require_human_for_state_change: bool = True
    require_administrator_for_destructive: bool = True

    require_sandbox: bool = True
    require_restricted_environment: bool = True
    require_output_limits: bool = True
    require_timeout: bool = True
    require_redaction: bool = True
    require_audit: bool = True
    require_structured_operation: bool = True
    reject_unknown_operation: bool = True
    reject_extra_arguments: bool = True
    reject_sensitive_arguments: bool = True

    capture_stdout: bool = True
    capture_stderr: bool = True
    truncate_oversized_output: bool = True
    preserve_raw_output: bool = False
    sanitize_output: bool = True
    redact_sensitive_output: bool = True
    include_output_in_audit: bool = False

    allow_cancellation: bool = True
    allow_rollback: bool = False
    require_confirmation_before_rollback: bool = True
    require_human_before_rollback: bool = True
    rollback_state_changes_only: bool = True

    fail_closed_on_unknown_adapter: bool = True
    fail_closed_on_unknown_target: bool = True
    fail_closed_on_unknown_risk: bool = True
    fail_closed_on_unknown_operation: bool = True
    fail_closed_on_invalid_arguments: bool = True
    fail_closed_on_sensitive_data: bool = True
    fail_closed_on_missing_grant: bool = True
    fail_closed_on_policy_error: bool = True

    def __post_init__(self) -> None:
        integer_fields = {
            "max_arguments_per_command", "max_argument_name_length", "max_string_argument_length",
            "default_timeout_seconds", "max_timeout_seconds", "max_output_bytes",
            "max_stdout_bytes", "max_stderr_bytes", "max_output_chunks",
            "max_output_chunk_bytes", "max_redactions", "max_errors", "max_metadata_depth",
            "max_metadata_items",
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
        for name in ("max_stdout_bytes", "max_stderr_bytes", "max_output_chunk_bytes"):
            if getattr(self, name) > self.max_output_bytes:
                raise ValueError(f"{name} must not exceed max_output_bytes")

    def is_adapter_allowed(self, adapter_type: LocalAdapterType) -> bool:
        self._require_enum("adapter_type", adapter_type, LocalAdapterType)
        return {
            LocalAdapterType.WINDOWS_SERVICE: self.allow_windows_service_adapter,
            LocalAdapterType.WINDOWS_EVENT_LOG: self.allow_windows_event_log_adapter,
            LocalAdapterType.SYSTEM_INFORMATION: self.allow_system_information_adapter,
            LocalAdapterType.PROCESS: self.allow_process_adapter,
            LocalAdapterType.NETWORK_DIAGNOSTIC: self.allow_network_diagnostic_adapter,
            LocalAdapterType.DISK_INFORMATION: self.allow_disk_information_adapter,
            LocalAdapterType.FILE_INFORMATION: self.allow_file_information_adapter,
            LocalAdapterType.UNKNOWN: self.allow_unknown_adapter,
        }[adapter_type]

    def is_target_allowed(self, target: ExecutionTarget) -> bool:
        self._require_enum("target", target, ExecutionTarget)
        return {
            ExecutionTarget.LOCAL_MACHINE: self.allow_local_execution,
            ExecutionTarget.WINDOWS: self.allow_windows_target,
            ExecutionTarget.NETWORK: self.allow_network_target,
            ExecutionTarget.LINUX: self.allow_linux_target,
            ExecutionTarget.REMOTE_AGENT: self.allow_remote_agent_target,
            ExecutionTarget.UNKNOWN: self.allow_unknown_target,
        }[target]

    def is_risk_allowed(self, risk: ExecutionRisk) -> bool:
        self._require_enum("risk", risk, ExecutionRisk)
        return {
            ExecutionRisk.LOW: self.allow_low_risk,
            ExecutionRisk.MEDIUM: self.allow_medium_risk,
            ExecutionRisk.HIGH: self.allow_high_risk,
            ExecutionRisk.CRITICAL: self.allow_critical_risk,
        }[risk]

    def is_operation_type_allowed(self, operation_type: LocalOperationType) -> bool:
        self._require_enum("operation_type", operation_type, LocalOperationType)
        return {
            LocalOperationType.READ_ONLY: self.allow_read_only_operations,
            LocalOperationType.STATE_CHANGING: self.allow_state_changing_operations,
            LocalOperationType.DESTRUCTIVE: self.allow_destructive_operations,
        }[operation_type]

    def validate_timeout(self, timeout_seconds: int) -> bool:
        return (
            isinstance(timeout_seconds, int)
            and not isinstance(timeout_seconds, bool)
            and 0 < timeout_seconds <= self.max_timeout_seconds
        )

    def validate_argument_count(self, count: int) -> bool:
        return (
            isinstance(count, int)
            and not isinstance(count, bool)
            and 0 <= count <= self.max_arguments_per_command
        )

    def validate_output_limits(self, stdout_bytes: int, stderr_bytes: int, total_bytes: int) -> bool:
        values = (stdout_bytes, stderr_bytes, total_bytes)
        return (
            all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in values)
            and stdout_bytes <= self.max_stdout_bytes
            and stderr_bytes <= self.max_stderr_bytes
            and total_bytes <= self.max_output_bytes
        )

    def requires_grant(self, operation_type: LocalOperationType) -> bool:
        self._require_enum("operation_type", operation_type, LocalOperationType)
        return self.require_valid_grant

    def requires_confirmation(self, operation_type: LocalOperationType) -> bool:
        self._require_enum("operation_type", operation_type, LocalOperationType)
        return operation_type != LocalOperationType.READ_ONLY and self.require_confirmation_for_state_change

    def requires_human(self, operation_type: LocalOperationType) -> bool:
        self._require_enum("operation_type", operation_type, LocalOperationType)
        return operation_type != LocalOperationType.READ_ONLY and self.require_human_for_state_change

    def can_execute_real_operation(
        self,
        *,
        adapter_type: LocalAdapterType,
        target: ExecutionTarget,
        risk: ExecutionRisk,
        operation_type: LocalOperationType,
    ) -> bool:
        return (
            self.allow_local_execution
            and self.allow_real_execution
            and self.is_adapter_allowed(adapter_type)
            and self.is_target_allowed(target)
            and self.is_risk_allowed(risk)
            and self.is_operation_type_allowed(operation_type)
        )

    def build_sandbox_policy(self) -> LocalSandboxPolicy:
        return LocalSandboxPolicy(
            allow_shell=self.allow_shell,
            allow_arbitrary_command=self.allow_arbitrary_commands,
            allow_environment_inheritance=self.allow_environment_inheritance,
            allow_network_access=self.allow_network_access,
            allow_filesystem_write=self.allow_filesystem_write,
            allow_registry_write=self.allow_registry_write,
            allow_service_state_change=self.allow_service_state_change,
            allow_process_termination=self.allow_process_termination,
            allow_elevation=self.allow_elevation,
            allow_child_processes=self.allow_child_processes,
            max_output_bytes=self.max_output_bytes,
            max_stderr_bytes=self.max_stderr_bytes,
            max_runtime_seconds=self.max_timeout_seconds,
            preserve_raw_output=self.preserve_raw_output,
            redact_sensitive_output=self.redact_sensitive_output,
        )

    @staticmethod
    def _require_enum(name: str, value: object, enum_type: type) -> None:
        if not isinstance(value, enum_type):
            raise ValueError(f"{name} must be a {enum_type.__name__}")
