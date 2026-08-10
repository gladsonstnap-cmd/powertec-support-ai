"""Strictly read-only adapter for allowlisted local process queries."""

import json
import platform
import re
from dataclasses import dataclass

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

try:
    import psutil as _process_backend
except ImportError:
    _process_backend = None


@dataclass(frozen=True)
class LocalProcessAdapter:
    """List processes by substring or query exact names without changing process state."""

    operation_names = frozenset({"list_processes", "read_system_process_information"})
    MAX_PROCESSES = 200
    MAX_NAME_LENGTH = 128
    _NAME_PATTERN = re.compile(r"^[A-Za-z0-9_. -]+$")
    _PATH_PATTERN = re.compile(r"(?i)(?:[A-Z]:[\\/]|\\\\)[^\s\"']+")
    _SECRET_PATTERN = re.compile(r"(?i)\b(password|token|secret|api_key)\s*=\s*[^\s,;]+")
    _STATUSES = frozenset(
        {"running", "sleeping", "stopped", "zombie", "idle", "disk_sleep", "dead"}
    )

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
            "redact_sensitive_output": contract.sandbox_policy.redact_sensitive_output,
        }
        if command.dry_run:
            return self._success(
                command.command_id,
                now_monotonic,
                "Dry-run: operação de processos validada; nenhuma consulta real foi realizada.",
                metadata,
            )
        if platform.system() != "Windows":
            return self._failed(
                command.command_id, now_monotonic,
                "Falha ao consultar processos do Windows.", metadata,
            )
        if _process_backend is None:
            return self._failed(
                command.command_id, now_monotonic,
                "Backend seguro de processos indisponível.", metadata,
            )
        arguments = {item.name: item.value for item in command.arguments}
        try:
            processes = self._collect_processes(_process_backend)
            if command.operation_name == "list_processes":
                name_filter = arguments.get("name_filter")
                if name_filter is not None:
                    folded = name_filter.casefold()
                    processes = [item for item in processes if folded in item["process_name"].casefold()]
                payload = {
                    "operation": "list_processes",
                    "process_count": len(processes),
                    "processes": processes,
                }
            else:
                process_name = arguments["process_name"]
                processes = [
                    item for item in processes
                    if item["process_name"].casefold() == process_name.casefold()
                ]
                payload = {
                    "operation": "read_system_process_information",
                    "process_name": process_name,
                    "match_count": len(processes),
                    "processes": processes,
                }
            output, truncated = self._bounded_json(
                payload, contract.sandbox_policy.max_output_bytes
            )
        except Exception:
            return self._failed(
                command.command_id, now_monotonic,
                "Falha ao consultar processos do Windows.", metadata,
            )
        return self._success(
            command.command_id, now_monotonic, output, metadata, truncated=truncated
        )

    def sanitize(self, raw_result: LocalRawExecutionResult) -> LocalSanitizedResult:
        if not isinstance(raw_result, LocalRawExecutionResult):
            raise ValueError("raw_result must be a LocalRawExecutionResult")
        max_bytes = raw_result.metadata.get("max_output_bytes", 1048576)
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            max_bytes = 1048576
        stdout = raw_result.stdout
        stderr = raw_result.stderr
        redactions: list[RedactedValue] = []
        if raw_result.metadata.get("redact_sensitive_output", True) is not False:
            stdout, stdout_redactions = self._redact_text(stdout)
            stderr, stderr_redactions = self._redact_text(stderr)
            redactions.extend((*stdout_redactions, *stderr_redactions))
        stdout, stdout_truncated = self._bounded_output(stdout, max_bytes)
        remaining = max(0, max_bytes - len(stdout.encode("utf-8")))
        stderr, stderr_truncated = self._truncate(stderr, remaining)
        return LocalSanitizedResult(
            command_id=raw_result.command_id,
            state=raw_result.state,
            exit_code=raw_result.exit_code,
            stdout_summary=stdout,
            stderr_summary=stderr,
            redactions=tuple(redactions),
            truncated=stdout_truncated or stderr_truncated,
            output_bytes=len(stdout.encode("utf-8")) + len(stderr.encode("utf-8")),
            errors=raw_result.errors,
            metadata={"sanitized": True},
        )

    def _collect_processes(self, backend: object) -> list[dict[str, object]]:
        collected: list[dict[str, object]] = []
        iterator = backend.process_iter(attrs=("pid", "name", "status"), ad_value=None)
        for process in iterator:
            try:
                info = process.info
                if not isinstance(info, dict):
                    continue
                pid = info.get("pid")
                name = info.get("name")
                if (
                    not isinstance(pid, int) or isinstance(pid, bool) or pid < 0
                    or not isinstance(name, str) or not name.strip()
                ):
                    continue
                collected.append(
                    {
                        "pid": pid,
                        "process_name": name[: self.MAX_NAME_LENGTH],
                        "status": self._status(info.get("status")),
                    }
                )
            except Exception as exc:
                if type(exc).__name__ in {"NoSuchProcess", "AccessDenied", "ZombieProcess"}:
                    continue
                continue
        collected.sort(key=lambda item: (item["process_name"].casefold(), item["pid"]))
        return collected[: self.MAX_PROCESSES]

    @classmethod
    def _status(cls, value: object) -> str:
        if not isinstance(value, str):
            return "unknown"
        normalized = value.strip().lower().replace("-", "_")
        return normalized if normalized in cls._STATUSES else "unknown"

    def _contract_error(self, contract: object, now_monotonic: object) -> str | None:
        if not isinstance(contract, LocalExecutionContract):
            return "Contrato local inválido."
        if not isinstance(now_monotonic, int | float) or isinstance(now_monotonic, bool) or now_monotonic < 0:
            return "Momento monotônico inválido."
        operation = contract.operation
        command = contract.command
        if operation.operation_name not in self.operation_names or command.operation_name != operation.operation_name:
            return "Operação local não suportada por este adapter."
        if operation.adapter_type != LocalAdapterType.PROCESS or command.adapter_type != LocalAdapterType.PROCESS:
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
        if not isinstance(command.dry_run, bool):
            return "Flag dry-run inválida."
        argument_error = self._argument_error(
            command.operation_name, command.arguments, operation.argument_names
        )
        if argument_error is not None:
            return argument_error
        sandbox = contract.sandbox_policy
        if any((
            sandbox.allow_shell, sandbox.allow_arbitrary_command,
            sandbox.allow_environment_inheritance, sandbox.allow_network_access,
            sandbox.allow_filesystem_write, sandbox.allow_registry_write,
            sandbox.allow_service_state_change, sandbox.allow_process_termination,
            sandbox.allow_elevation, sandbox.allow_child_processes,
        )):
            return "Sandbox incompatível com consulta read-only."
        return None

    def _argument_error(
        self, operation_name: str, arguments: object, catalog_names: tuple[str, ...]
    ) -> str | None:
        expected = {
            "list_processes": ("name_filter",),
            "read_system_process_information": ("process_name",),
        }[operation_name]
        if catalog_names != expected:
            return "Catálogo de argumentos incompatível."
        values = tuple(arguments)
        names = tuple(item.name for item in values)
        if len(set(names)) != len(names) or any(name not in expected for name in names):
            return "Argumentos incompatíveis com consulta de processos."
        if operation_name == "read_system_process_information" and "process_name" not in names:
            return "process_name é obrigatório."
        if not values:
            return None
        value = values[0].value
        if (
            not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > self.MAX_NAME_LENGTH
            or self._NAME_PATTERN.fullmatch(value) is None
        ):
            return "Identificador de processo inválido."
        return None

    def _redact_text(self, value: str) -> tuple[str, tuple[RedactedValue, ...]]:
        redactions: list[RedactedValue] = []
        value, path_count = self._PATH_PATTERN.subn("[REDACTED_PATH]", value)
        redactions.extend(
            RedactedValue("[REDACTED_PATH]", RedactionReason.PERSONAL_DATA)
            for _ in range(path_count)
        )

        def replace_secret(match: re.Match) -> str:
            label = match.group(1).lower()
            reason = {
                "password": RedactionReason.PASSWORD,
                "token": RedactionReason.TOKEN,
                "secret": RedactionReason.SECRET,
                "api_key": RedactionReason.API_KEY,
            }[label]
            redactions.append(RedactedValue(f"{label}=[REDACTED]", reason))
            return f"{label}=[REDACTED]"

        return self._SECRET_PATTERN.sub(replace_secret, value), tuple(redactions)

    @classmethod
    def _bounded_json(cls, payload: dict[str, object], maximum_bytes: int) -> tuple[str, bool]:
        copied = {**payload, "processes": list(payload.get("processes", []))}
        count_key = "process_count" if "process_count" in copied else "match_count"
        truncated = False
        while True:
            output = json.dumps(copied, sort_keys=True, separators=(",", ":"))
            if len(output.encode("utf-8")) <= maximum_bytes:
                return output, truncated
            if copied["processes"]:
                copied["processes"].pop()
                copied[count_key] = len(copied["processes"])
                copied["truncated"] = True
                truncated = True
                continue
            return cls._truncate('{"truncated":true}', maximum_bytes)[0], True

    @classmethod
    def _bounded_output(cls, value: str, maximum_bytes: int) -> tuple[str, bool]:
        try:
            payload = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return cls._truncate(value, maximum_bytes)
        if isinstance(payload, dict) and isinstance(payload.get("processes"), list):
            return cls._bounded_json(payload, maximum_bytes)
        return cls._truncate(value, maximum_bytes)

    @staticmethod
    def _success(
        command_id: str, now: float, output: str, metadata: dict[str, object],
        *, truncated: bool = False,
    ) -> LocalRawExecutionResult:
        chunk = LocalOutputChunk(
            sequence=0, stream=OutputStreamType.STDOUT, content=output,
            truncated=truncated, redacted=False, redaction_reasons=(),
            occurred_at_monotonic=now,
        )
        return LocalRawExecutionResult(
            command_id=command_id, state=LocalExecutionState.SUCCESS,
            started_at_monotonic=now, finished_at_monotonic=now, exit_code=0,
            stdout=output, stderr="", output_chunks=(chunk,), timed_out=False,
            cancelled=False, metadata=metadata,
        )

    @staticmethod
    def _failed(
        command_id: str, now: object, message: str,
        metadata: dict[str, object] | None = None,
    ) -> LocalRawExecutionResult:
        timestamp = (
            float(now) if isinstance(now, int | float) and not isinstance(now, bool) and now >= 0
            else None
        )
        return LocalRawExecutionResult(
            command_id=command_id, state=LocalExecutionState.FAILED,
            started_at_monotonic=timestamp, finished_at_monotonic=timestamp,
            exit_code=None, stdout="", stderr=message, output_chunks=(),
            timed_out=False, cancelled=False, metadata=metadata or {}, errors=(message,),
        )

    @staticmethod
    def _truncate(value: str, maximum_bytes: int) -> tuple[str, bool]:
        encoded = value.encode("utf-8")
        if len(encoded) <= maximum_bytes:
            return value, False
        return encoded[:maximum_bytes].decode("utf-8", errors="ignore"), True
