"""Strictly read-only adapter for two allowlisted Windows service operations."""

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
    import win32service as _service_backend
except ImportError:
    _service_backend = None


class _ServiceNotFound(Exception):
    pass


@dataclass(frozen=True)
class LocalWindowsServiceAdapter:
    """List or query Windows services without changing service state or configuration."""

    operation_names = frozenset({"list_windows_services", "check_service_status"})
    MAX_SERVICES = 200
    MAX_NAME_LENGTH = 128
    _NAME_PATTERN = re.compile(r"^[A-Za-z0-9_. -]+$")
    _PATH_PATTERN = re.compile(r"(?i)(?:[A-Z]:[\\/]|\\\\)[^\s\"']+")
    _SECRET_PATTERN = re.compile(r"(?i)\b(password|token|secret|api_key)\s*=\s*[^\s,;]+")

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
            message = "Dry-run: operação de serviços validada; nenhuma consulta real foi realizada."
            return self._success(command.command_id, now_monotonic, message, metadata)
        if platform.system() != "Windows":
            return self._failed(
                command.command_id, now_monotonic,
                "Falha ao consultar serviços do Windows.", metadata,
            )
        if _service_backend is None:
            return self._failed(
                command.command_id, now_monotonic,
                "Backend seguro de serviços do Windows indisponível.", metadata,
            )
        arguments = {item.name: item.value for item in command.arguments}
        try:
            if command.operation_name == "list_windows_services":
                payload = self._list_services(_service_backend, arguments.get("name_filter"))
            else:
                payload = self._check_service(_service_backend, arguments["service_name"])
            output, output_truncated = self._bounded_json(
                payload, contract.sandbox_policy.max_output_bytes
            )
        except _ServiceNotFound:
            return self._failed(
                command.command_id, now_monotonic, "Serviço não encontrado.", metadata,
            )
        except Exception:
            return self._failed(
                command.command_id, now_monotonic,
                "Falha ao consultar serviços do Windows.", metadata,
            )
        return self._success(
            command.command_id, now_monotonic, output, metadata, truncated=output_truncated,
        )

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
            stdout_summary, stdout_redactions = self._redact_text(stdout_summary)
            stderr_summary, stderr_redactions = self._redact_text(stderr_summary)
            redactions.extend((*stdout_redactions, *stderr_redactions))
        stdout_summary, stdout_truncated = self._bounded_output(stdout_summary, max_bytes)
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

    def _list_services(self, backend: object, name_filter: str | None) -> dict[str, object]:
        manager = None
        close_error = False
        try:
            manager = backend.OpenSCManager(None, None, backend.SC_MANAGER_ENUMERATE_SERVICE)
            records = backend.EnumServicesStatus(
                manager, backend.SERVICE_WIN32, backend.SERVICE_STATE_ALL
            )
            services = []
            normalized_filter = name_filter.casefold() if name_filter is not None else None
            for record in records:
                service_name, display_name, status_data = record
                if not isinstance(service_name, str) or not isinstance(display_name, str):
                    continue
                if normalized_filter is not None and normalized_filter not in service_name.casefold():
                    continue
                current_state = (
                    status_data.get("CurrentState", 0)
                    if isinstance(status_data, dict)
                    else 0
                )
                services.append(
                    {
                        "display_name": display_name[:256],
                        "service_name": service_name[: self.MAX_NAME_LENGTH],
                        "startup_type": "unknown",
                        "status": self._status(current_state),
                    }
                )
            services.sort(key=lambda item: item["service_name"].casefold())
            services = services[: self.MAX_SERVICES]
        finally:
            if manager is not None:
                try:
                    backend.CloseServiceHandle(manager)
                except Exception:
                    close_error = True
        if close_error:
            raise RuntimeError("manager close failed")
        return {
            "operation": "list_windows_services",
            "service_count": len(services),
            "services": services,
        }

    def _check_service(self, backend: object, service_name: str) -> dict[str, object]:
        manager = None
        service = None
        close_error = False
        try:
            manager = backend.OpenSCManager(None, None, backend.SC_MANAGER_CONNECT)
            try:
                service = backend.OpenService(
                    manager,
                    service_name,
                    backend.SERVICE_QUERY_STATUS | backend.SERVICE_QUERY_CONFIG,
                )
            except Exception as exc:
                if getattr(exc, "winerror", None) == 1060:
                    raise _ServiceNotFound() from None
                raise
            status_data = backend.QueryServiceStatus(service)
            config_data = backend.QueryServiceConfig(service)
            current_state = status_data[1] if isinstance(status_data, tuple) and len(status_data) > 1 else 0
            start_type = config_data[1] if isinstance(config_data, tuple) and len(config_data) > 1 else 0
            display_name = (
                config_data[8]
                if isinstance(config_data, tuple) and len(config_data) > 8 and isinstance(config_data[8], str)
                else service_name
            )
            projected = {
                "display_name": display_name[:256],
                "service_name": service_name,
                "startup_type": self._startup_type(start_type),
                "status": self._status(current_state),
            }
        finally:
            if service is not None:
                try:
                    backend.CloseServiceHandle(service)
                except Exception:
                    close_error = True
            if manager is not None:
                try:
                    backend.CloseServiceHandle(manager)
                except Exception:
                    close_error = True
        if close_error:
            raise RuntimeError("service handle close failed")
        return {"operation": "check_service_status", "service": projected}

    @staticmethod
    def _status(value: object) -> str:
        return {
            1: "stopped",
            2: "start_pending",
            3: "stop_pending",
            4: "running",
            5: "continue_pending",
            6: "pause_pending",
            7: "paused",
        }.get(value, "unknown")

    @staticmethod
    def _startup_type(value: object) -> str:
        return {2: "automatic", 3: "manual", 4: "disabled"}.get(value, "unknown")

    def _contract_error(self, contract: object, now_monotonic: object) -> str | None:
        if not isinstance(contract, LocalExecutionContract):
            return "Contrato local inválido."
        if not isinstance(now_monotonic, int | float) or isinstance(now_monotonic, bool) or now_monotonic < 0:
            return "Momento monotônico inválido."
        operation = contract.operation
        command = contract.command
        if operation.operation_name not in self.operation_names or command.operation_name != operation.operation_name:
            return "Operação local não suportada por este adapter."
        if operation.adapter_type != LocalAdapterType.WINDOWS_SERVICE or command.adapter_type != LocalAdapterType.WINDOWS_SERVICE:
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
        error = self._argument_error(command.operation_name, command.arguments, operation.argument_names)
        if error is not None:
            return error
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
            return "Sandbox incompatível com consulta read-only."
        return None

    def _argument_error(
        self,
        operation_name: str,
        arguments: object,
        catalog_names: tuple[str, ...],
    ) -> str | None:
        expected = {
            "list_windows_services": ("name_filter",),
            "check_service_status": ("service_name",),
        }[operation_name]
        if catalog_names != expected:
            return "Catálogo de argumentos incompatível."
        values = tuple(arguments)
        names = tuple(item.name for item in values)
        if len(set(names)) != len(names) or any(name not in expected for name in names):
            return "Argumentos incompatíveis com consulta de serviços."
        required = operation_name == "check_service_status"
        if required and "service_name" not in names:
            return "service_name é obrigatório."
        if not values:
            return None
        value = values[0].value
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or len(value) > self.MAX_NAME_LENGTH
            or self._NAME_PATTERN.fullmatch(value) is None
        ):
            return "Identificador de serviço inválido."
        return None

    def _redact_text(self, value: str) -> tuple[str, tuple[RedactedValue, ...]]:
        redactions: list[RedactedValue] = []
        value, path_count = self._PATH_PATTERN.subn("[REDACTED_PATH]", value)
        for _ in range(path_count):
            redactions.append(RedactedValue("[REDACTED_PATH]", RedactionReason.PERSONAL_DATA))

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
        copied = {**payload}
        if isinstance(payload.get("services"), list):
            copied["services"] = list(payload["services"])
        truncated = False
        while True:
            output = json.dumps(copied, sort_keys=True, separators=(",", ":"))
            if len(output.encode("utf-8")) <= maximum_bytes:
                return output, truncated
            if isinstance(copied.get("services"), list) and copied["services"]:
                copied["services"].pop()
                copied["service_count"] = len(copied["services"])
                copied["truncated"] = True
                truncated = True
                continue
            minimal = '{"truncated":true}'
            return cls._truncate(minimal, maximum_bytes)[0], True

    @classmethod
    def _bounded_output(cls, value: str, maximum_bytes: int) -> tuple[str, bool]:
        try:
            payload = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return cls._truncate(value, maximum_bytes)
        if isinstance(payload, dict) and isinstance(payload.get("services"), list):
            return cls._bounded_json(payload, maximum_bytes)
        return cls._truncate(value, maximum_bytes)

    @staticmethod
    def _success(
        command_id: str,
        now_monotonic: float,
        output: str,
        metadata: dict[str, object],
        *,
        truncated: bool = False,
    ) -> LocalRawExecutionResult:
        chunk = LocalOutputChunk(
            sequence=0,
            stream=OutputStreamType.STDOUT,
            content=output,
            truncated=truncated,
            redacted=False,
            redaction_reasons=(),
            occurred_at_monotonic=now_monotonic,
        )
        return LocalRawExecutionResult(
            command_id=command_id, state=LocalExecutionState.SUCCESS,
            started_at_monotonic=now_monotonic, finished_at_monotonic=now_monotonic,
            exit_code=0, stdout=output, stderr="", output_chunks=(chunk,),
            timed_out=False, cancelled=False, metadata=metadata,
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
