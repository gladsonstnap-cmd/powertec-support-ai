"""Strictly read-only adapter for allowlisted Windows disk information."""

import json
import ntpath
import platform
import re
import shutil
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


class LocalDiskInformationAdapter:
    """Read basic disk capacity data without shell, network, or filesystem writes."""

    operation_names = frozenset({"check_disk_information", "check_disk_space"})
    _ARGUMENT_BY_OPERATION = {
        "check_disk_information": "disk_name",
        "check_disk_space": "drive",
    }
    _DRIVE_PATTERN = re.compile(r"^[A-Za-z]:$")
    _ARBITRARY_PATH_PATTERN = re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/][^\s\"']+")

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
            message = "Dry-run: operação de disco validada; nenhuma leitura real foi realizada."
            return self._success(command.command_id, now_monotonic, message, metadata)

        argument = self._argument_value(contract)
        try:
            if platform.system() != "Windows":
                raise RuntimeError("unsupported host")
            drive = argument if argument is not None else self._system_drive()
            if command.operation_name == "check_disk_space":
                output = self._collect_space(drive)
            else:
                output = self._collect_information(drive)
            serialized = json.dumps(output, sort_keys=True, separators=(",", ":"))
        except Exception:
            message = (
                "Falha ao consultar espaço em disco."
                if command.operation_name == "check_disk_space"
                else "Falha ao coletar informações de disco."
            )
            return self._failed(command.command_id, now_monotonic, message, metadata)
        return self._success(command.command_id, now_monotonic, serialized, metadata)

    def sanitize(self, raw_result: LocalRawExecutionResult) -> LocalSanitizedResult:
        if not isinstance(raw_result, LocalRawExecutionResult):
            raise ValueError("raw_result must be a LocalRawExecutionResult")
        max_bytes = raw_result.metadata.get("max_output_bytes", 1048576)
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            max_bytes = 1048576
        stdout_summary = raw_result.stdout
        stderr_summary = raw_result.stderr
        redactions: list[RedactedValue] = []
        if raw_result.metadata.get("redact_sensitive_output", True) is not False:
            stdout_summary, count = self._ARBITRARY_PATH_PATTERN.subn("[REDACTED_PATH]", stdout_summary)
            stderr_summary, stderr_count = self._ARBITRARY_PATH_PATTERN.subn("[REDACTED_PATH]", stderr_summary)
            for _ in range(count + stderr_count):
                redactions.append(
                    RedactedValue(
                        placeholder="[REDACTED_PATH]",
                        reason=RedactionReason.PERSONAL_DATA,
                    )
                )
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
    def _collect_space(drive: str) -> dict[str, object]:
        usage = shutil.disk_usage(f"{drive}\\")
        total = int(usage.total)
        used = int(usage.used)
        free = int(usage.free)
        return {
            "drive": drive.upper(),
            "free_bytes": free,
            "total_bytes": total,
            "usage_percent": used / total * 100 if total else 0.0,
            "used_bytes": used,
        }

    @classmethod
    def _collect_information(cls, drive: str) -> dict[str, object]:
        usage = shutil.disk_usage(f"{drive}\\")
        return {
            "device": drive.upper(),
            "filesystem_type": "",
            "free_bytes": int(usage.free),
            "mountpoint": drive.upper(),
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
        }

    @classmethod
    def _system_drive(cls) -> str:
        if platform.system() != "Windows":
            raise RuntimeError("unsupported host")
        drive, _ = ntpath.splitdrive(sys.executable)
        if not cls._valid_drive(drive):
            raise RuntimeError("system drive unavailable")
        return drive.upper()

    def _contract_error(self, contract: object, now_monotonic: object) -> str | None:
        if not isinstance(contract, LocalExecutionContract):
            return "Contrato local inválido."
        if not isinstance(now_monotonic, int | float) or isinstance(now_monotonic, bool) or now_monotonic < 0:
            return "Momento monotônico inválido."
        operation = contract.operation
        command = contract.command
        if operation.operation_name not in self.operation_names or command.operation_name != operation.operation_name:
            return "Operação local não suportada por este adapter."
        if operation.adapter_type != LocalAdapterType.DISK_INFORMATION or command.adapter_type != LocalAdapterType.DISK_INFORMATION:
            return "Adapter local incompatível."
        if operation.operation_type != LocalOperationType.READ_ONLY or command.operation_type != LocalOperationType.READ_ONLY:
            return "Tipo de operação incompatível."
        if command.target != ExecutionTarget.WINDOWS or ExecutionTarget.WINDOWS not in operation.allowed_targets:
            return "Target local incompatível."
        if command.risk != ExecutionRisk.LOW or ExecutionRisk.LOW not in operation.allowed_risks:
            return "Risco local incompatível."
        if contract.state not in {LocalExecutionState.PENDING, LocalExecutionState.VALIDATED, LocalExecutionState.READY}:
            return "Estado do contrato incompatível."
        expected_argument = self._ARGUMENT_BY_OPERATION[command.operation_name]
        if operation.argument_names != (expected_argument,):
            return "Catálogo de argumentos incompatível."
        if len(command.arguments) > 1 or any(item.name != expected_argument for item in command.arguments):
            return "Argumentos incompatíveis com a operação de disco."
        if command.arguments and not self._valid_drive(command.arguments[0].value):
            return "Identificador de disco inválido."
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
    def _argument_value(contract: LocalExecutionContract) -> str | None:
        return str(contract.command.arguments[0].value).upper() if contract.command.arguments else None

    @classmethod
    def _valid_drive(cls, value: object) -> bool:
        return isinstance(value, str) and cls._DRIVE_PATTERN.fullmatch(value) is not None

    @staticmethod
    def _success(
        command_id: str,
        now_monotonic: float,
        output: str,
        metadata: dict[str, object],
    ) -> LocalRawExecutionResult:
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
            command_id=command_id,
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
