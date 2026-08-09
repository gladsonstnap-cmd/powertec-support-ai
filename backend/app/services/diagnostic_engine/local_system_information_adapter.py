"""Read-only adapter for the single allowlisted system-information operation."""

import json
import os
import platform
import sys

from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType,
    LocalExecutionContract,
    LocalExecutionState,
    LocalOperationType,
    LocalOutputChunk,
    LocalRawExecutionResult,
    LocalSanitizedResult,
    OutputStreamType,
    RedactedValue,
    RedactionReason,
)


class LocalSystemInformationAdapter:
    """Collect basic immutable host facts without shell, network, or writes."""

    operation_name = "read_system_information"

    def execute(
        self,
        contract: LocalExecutionContract,
        now_monotonic: float,
    ) -> LocalRawExecutionResult:
        error = self._contract_error(contract, now_monotonic)
        if error is not None:
            command_id = getattr(getattr(contract, "command", None), "command_id", "invalid-command")
            return self._failed(command_id, now_monotonic, error)
        command = contract.command
        metadata = {
            "max_output_bytes": contract.sandbox_policy.max_output_bytes,
            "preserve_raw_output": contract.sandbox_policy.preserve_raw_output,
            "redact_sensitive_output": contract.sandbox_policy.redact_sensitive_output,
        }
        if command.dry_run:
            message = "Dry-run: read_system_information validada; nenhuma coleta real realizada."
            chunk = LocalOutputChunk(
                sequence=0,
                stream=OutputStreamType.STDOUT,
                content=message,
                truncated=False,
                redacted=False,
                redaction_reasons=(),
                occurred_at_monotonic=now_monotonic,
            )
            return LocalRawExecutionResult(
                command_id=command.command_id,
                state=LocalExecutionState.SUCCESS,
                started_at_monotonic=now_monotonic,
                finished_at_monotonic=now_monotonic,
                exit_code=0,
                stdout=message,
                stderr="",
                output_chunks=(chunk,),
                timed_out=False,
                cancelled=False,
                metadata=metadata,
            )
        try:
            information = self._collect(contract.sandbox_policy.preserve_raw_output)
            output = json.dumps(information, sort_keys=True, separators=(",", ":"))
        except Exception:
            return self._failed(
                command.command_id,
                now_monotonic,
                "Falha ao coletar informações do sistema.",
                metadata,
            )
        chunk = LocalOutputChunk(
            sequence=0,
            stream=OutputStreamType.STDOUT,
            content=output,
            truncated=False,
            redacted=False,
            redaction_reasons=(),
            occurred_at_monotonic=now_monotonic,
        )
        return LocalRawExecutionResult(
            command_id=command.command_id,
            state=LocalExecutionState.SUCCESS,
            started_at_monotonic=now_monotonic,
            finished_at_monotonic=now_monotonic,
            exit_code=0,
            stdout=output,
            stderr="",
            output_chunks=(chunk,),
            timed_out=False,
            cancelled=False,
            metadata=metadata,
        )

    def sanitize(self, raw_result: LocalRawExecutionResult) -> LocalSanitizedResult:
        if not isinstance(raw_result, LocalRawExecutionResult):
            raise ValueError("raw_result must be a LocalRawExecutionResult")
        max_bytes = raw_result.metadata.get("max_output_bytes", 1048576)
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            max_bytes = 1048576
        stdout_summary = raw_result.stdout
        stderr_summary = raw_result.stderr
        redactions = []
        should_redact = raw_result.metadata.get("redact_sensitive_output", True) is not False
        try:
            data = json.loads(stdout_summary)
        except (TypeError, ValueError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict) and "hostname" in data and should_redact:
            hostname = data.pop("hostname")
            redactions.append(
                RedactedValue(
                    placeholder="[REDACTED_HOSTNAME]",
                    reason=RedactionReason.PERSONAL_DATA,
                    original_length=len(hostname) if isinstance(hostname, str) else None,
                )
            )
            data["hostname"] = "[REDACTED_HOSTNAME]"
            stdout_summary = json.dumps(data, sort_keys=True, separators=(",", ":"))
        stdout_summary, stdout_truncated = self._truncate(stdout_summary, max_bytes)
        remaining = max(0, max_bytes - len(stdout_summary.encode("utf-8")))
        stderr_summary, stderr_truncated = self._truncate(stderr_summary, remaining)
        output_bytes = len(stdout_summary.encode("utf-8")) + len(stderr_summary.encode("utf-8"))
        return LocalSanitizedResult(
            command_id=raw_result.command_id,
            state=raw_result.state,
            exit_code=raw_result.exit_code,
            stdout_summary=stdout_summary,
            stderr_summary=stderr_summary,
            redactions=tuple(redactions),
            truncated=stdout_truncated or stderr_truncated,
            output_bytes=output_bytes,
            errors=raw_result.errors,
            metadata={"sanitized": True},
        )

    @staticmethod
    def _collect(include_hostname: bool) -> dict[str, object]:
        operating_system = platform.system()
        if operating_system != "Windows":
            raise RuntimeError("unsupported host")
        values = {
            "operating_system": operating_system,
            "operating_system_release": platform.release(),
            "operating_system_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "python_platform": sys.platform,
            "cpu_count": os.cpu_count(),
        }
        if include_hostname:
            values["hostname"] = platform.node()
        return {key: value for key, value in values.items() if value is not None}

    def _contract_error(
        self, contract: object, now_monotonic: object
    ) -> str | None:
        if not isinstance(contract, LocalExecutionContract):
            return "Contrato local inválido."
        if not isinstance(now_monotonic, int | float) or isinstance(now_monotonic, bool) or now_monotonic < 0:
            return "Momento monotônico inválido."
        operation = contract.operation
        command = contract.command
        if operation.operation_name != self.operation_name or command.operation_name != self.operation_name:
            return "Operação local não suportada por este adapter."
        if operation.adapter_type != LocalAdapterType.SYSTEM_INFORMATION or command.adapter_type != LocalAdapterType.SYSTEM_INFORMATION:
            return "Adapter local incompatível."
        if operation.operation_type != LocalOperationType.READ_ONLY or command.operation_type != LocalOperationType.READ_ONLY:
            return "Tipo de operação incompatível."
        if command.target != ExecutionTarget.WINDOWS or ExecutionTarget.WINDOWS not in operation.allowed_targets:
            return "Target local incompatível."
        if command.risk != ExecutionRisk.LOW or ExecutionRisk.LOW not in operation.allowed_risks:
            return "Risco local incompatível."
        if contract.state not in {
            LocalExecutionState.PENDING,
            LocalExecutionState.VALIDATED,
            LocalExecutionState.READY,
        }:
            return "Estado do contrato incompatível."
        if command.arguments:
            return "read_system_information não aceita argumentos."
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
            return "Sandbox incompatível com coleta read-only."
        return None

    @staticmethod
    def _failed(
        command_id: str,
        now_monotonic: object,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> LocalRawExecutionResult:
        timestamp = (
            float(now_monotonic)
            if isinstance(now_monotonic, int | float) and not isinstance(now_monotonic, bool) and now_monotonic >= 0
            else None
        )
        return LocalRawExecutionResult(
            command_id=command_id,
            state=LocalExecutionState.FAILED,
            started_at_monotonic=timestamp,
            finished_at_monotonic=timestamp,
            exit_code=None,
            stdout="",
            stderr=message,
            output_chunks=(),
            timed_out=False,
            cancelled=False,
            metadata=metadata or {},
            errors=(message,),
        )

    @staticmethod
    def _truncate(value: str, maximum_bytes: int) -> tuple[str, bool]:
        encoded = value.encode("utf-8")
        if len(encoded) <= maximum_bytes:
            return value, False
        return encoded[:maximum_bytes].decode("utf-8", errors="ignore"), True
