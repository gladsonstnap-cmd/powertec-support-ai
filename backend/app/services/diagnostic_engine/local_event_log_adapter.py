"""Strictly read-only adapter for the allowlisted Windows Event Log operation."""

import json
import math
import platform
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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
    import win32evtlog as _event_log_backend
except ImportError:
    _event_log_backend = None


@dataclass(frozen=True)
class LocalEventLogAdapter:
    """Collect a bounded diagnostic projection of System or Application events."""

    operation_name = "collect_event_logs"
    allowed_logs = ("Application", "System")
    MAX_EVENTS = 100
    MAX_HOURS = 168
    MAX_MESSAGE_CHARS = 500
    _PATH_PATTERN = re.compile(r"(?i)(?:[A-Z]:[\\/]|\\\\)[^\s\"']+")
    _SECRET_PATTERN = re.compile(
        r"(?i)\b(password|token|secret|api_key)\s*=\s*[^\s,;]+"
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
            message = "Dry-run: collect_event_logs validada; nenhum Event Log foi consultado."
            return self._success(command.command_id, now_monotonic, message, metadata)
        if platform.system() != "Windows":
            return self._failed(
                command.command_id,
                now_monotonic,
                "Falha ao coletar eventos do Windows.",
                metadata,
            )
        if _event_log_backend is None:
            return self._failed(
                command.command_id,
                now_monotonic,
                "Backend seguro de Event Log indisponível.",
                metadata,
            )
        arguments = {item.name: item.value for item in command.arguments}
        try:
            payload = self._collect(
                _event_log_backend,
                arguments["log_name"],
                int(arguments.get("hours", 24)),
            )
            output, output_truncated = self._bounded_json(
                payload, contract.sandbox_policy.max_output_bytes
            )
        except Exception:
            return self._failed(
                command.command_id,
                now_monotonic,
                "Falha ao coletar eventos do Windows.",
                metadata,
            )
        return self._success(
            command.command_id,
            now_monotonic,
            output,
            metadata,
            truncated=output_truncated,
        )

    def sanitize(self, raw_result: LocalRawExecutionResult) -> LocalSanitizedResult:
        if not isinstance(raw_result, LocalRawExecutionResult):
            raise ValueError("raw_result must be a LocalRawExecutionResult")
        max_bytes = raw_result.metadata.get("max_output_bytes", 1048576)
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            max_bytes = 1048576
        redactions: list[RedactedValue] = []
        stdout_summary = raw_result.stdout
        stderr_summary = raw_result.stderr
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

    def _collect(self, backend: object, log_name: str, hours: int) -> dict[str, object]:
        handle = None
        events: list[dict[str, object]] = []
        seen: set[tuple[object, ...]] = set()
        cutoff = self._utc_now() - timedelta(hours=hours)
        close_error = False
        try:
            handle = backend.OpenEventLog(None, log_name)
            flags = backend.EVENTLOG_BACKWARDS_READ | backend.EVENTLOG_SEQUENTIAL_READ
            stop = False
            while len(events) < self.MAX_EVENTS and not stop:
                batch = backend.ReadEventLog(handle, flags, 0)
                if not batch:
                    break
                for event in batch:
                    timestamp_value = self._event_timestamp(event)
                    if timestamp_value is not None and timestamp_value < cutoff:
                        stop = True
                        break
                    projected = self._project_event(event, log_name)
                    identity = (
                        projected["event_id"], projected["source"], projected["timestamp"],
                        projected["category"], projected["message_summary"],
                    )
                    if identity not in seen:
                        seen.add(identity)
                        events.append(projected)
                    if len(events) >= self.MAX_EVENTS:
                        break
        finally:
            if handle is not None:
                try:
                    backend.CloseEventLog(handle)
                except Exception:
                    close_error = True
        if close_error:
            raise RuntimeError("event log handle close failed")
        return {
            "event_count": len(events),
            "events": events,
            "log_name": log_name,
            "operation": self.operation_name,
        }

    def _project_event(self, event: object, log_name: str) -> dict[str, object]:
        event_id = getattr(event, "EventID", 0)
        if not isinstance(event_id, int) or isinstance(event_id, bool):
            event_id = 0
        category = getattr(event, "EventCategory", 0)
        if not isinstance(category, int) or isinstance(category, bool):
            category = 0
        source = getattr(event, "SourceName", "")
        source = source if isinstance(source, str) else ""
        summary_values = getattr(event, "StringInserts", ()) or ()
        summary = " ".join(str(value) for value in tuple(summary_values)[:3])
        summary, _ = self._redact_text(summary[: self.MAX_MESSAGE_CHARS])
        return {
            "category": category,
            "event_id": event_id & 0xFFFF,
            "log_name": log_name,
            "message_summary": summary,
            "severity": self._severity(getattr(event, "EventType", 0)),
            "source": source[:128],
            "timestamp": self._timestamp_text(event),
        }

    @staticmethod
    def _severity(event_type: object) -> str:
        return {
            1: "error",
            2: "warning",
            4: "information",
            8: "audit_success",
            16: "audit_failure",
        }.get(event_type, "unknown")

    @staticmethod
    def _event_timestamp(event: object) -> datetime | None:
        value = getattr(event, "TimeGenerated", None)
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _timestamp_text(cls, event: object) -> str:
        value = cls._event_timestamp(event)
        return value.isoformat() if value is not None else ""

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _contract_error(self, contract: object, now_monotonic: object) -> str | None:
        if not isinstance(contract, LocalExecutionContract):
            return "Contrato local inválido."
        if not isinstance(now_monotonic, int | float) or isinstance(now_monotonic, bool) or now_monotonic < 0:
            return "Momento monotônico inválido."
        operation = contract.operation
        command = contract.command
        if operation.operation_name != self.operation_name or command.operation_name != self.operation_name:
            return "Operação local não suportada por este adapter."
        if operation.adapter_type != LocalAdapterType.WINDOWS_EVENT_LOG or command.adapter_type != LocalAdapterType.WINDOWS_EVENT_LOG:
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
        error = self._argument_error(command.arguments, operation.argument_names)
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
            return "Sandbox incompatível com coleta read-only."
        return None

    def _argument_error(self, arguments: object, catalog_names: tuple[str, ...]) -> str | None:
        values = tuple(arguments)
        if catalog_names != ("log_name", "hours"):
            return "Catálogo de argumentos incompatível."
        names = tuple(item.name for item in values)
        if len(set(names)) != len(names) or any(name not in catalog_names for name in names):
            return "Argumentos incompatíveis com collect_event_logs."
        if "log_name" not in names:
            return "log_name é obrigatório."
        supplied = {item.name: item.value for item in values}
        log_name = supplied["log_name"]
        if not isinstance(log_name, str) or log_name not in self.allowed_logs:
            return "Log do Windows não permitido."
        hours = supplied.get("hours", 24)
        if (
            not isinstance(hours, int)
            or isinstance(hours, bool)
            or not math.isfinite(hours)
            or not 1 <= hours <= self.MAX_HOURS
        ):
            return "Janela temporal inválida."
        return None

    def _redact_text(self, value: str) -> tuple[str, tuple[RedactedValue, ...]]:
        redactions: list[RedactedValue] = []
        value, path_count = self._PATH_PATTERN.subn("[REDACTED_PATH]", value)
        for _ in range(path_count):
            redactions.append(
                RedactedValue("[REDACTED_PATH]", RedactionReason.PERSONAL_DATA)
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

        value = self._SECRET_PATTERN.sub(replace_secret, value)
        return value, tuple(redactions)

    @classmethod
    def _bounded_json(cls, payload: dict[str, object], maximum_bytes: int) -> tuple[str, bool]:
        copied = {**payload, "events": list(payload.get("events", []))}
        truncated = False
        while True:
            output = json.dumps(copied, sort_keys=True, separators=(",", ":"))
            if len(output.encode("utf-8")) <= maximum_bytes:
                return output, truncated
            if copied["events"]:
                copied["events"].pop()
                copied["event_count"] = len(copied["events"])
                copied["truncated"] = True
                truncated = True
                continue
            minimal = '{"truncated":true}'
            if len(minimal.encode("utf-8")) <= maximum_bytes:
                return minimal, True
            return cls._truncate(minimal, maximum_bytes)[0], True

    @classmethod
    def _bounded_output(cls, value: str, maximum_bytes: int) -> tuple[str, bool]:
        try:
            payload = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return cls._truncate(value, maximum_bytes)
        if isinstance(payload, dict) and isinstance(payload.get("events"), list):
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
