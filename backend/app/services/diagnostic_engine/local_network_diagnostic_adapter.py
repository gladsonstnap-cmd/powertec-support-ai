"""Read-only local network configuration adapter with no active network traffic."""

import json
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
    import psutil as _network_backend
except ImportError:
    _network_backend = None


@dataclass(frozen=True)
class LocalNetworkDiagnosticAdapter:
    """Collect bounded local interface configuration without probing the network."""

    operation_names = frozenset({"check_network_configuration"})
    MAX_INTERFACES = 64
    MAX_ADDRESSES = 256
    MAX_TEXT_LENGTH = 256
    _PATH_PATTERN = re.compile(
        r"(?i)(?:[A-Z]:[\\/]|\\\\|/(?:home|users)/)[^\s\"']+"
    )
    _SECRET_PATTERN = re.compile(
        r"(?i)\b(password|token|secret|api_key|authorization|cookie)\s*=\s*[^\s,;]+"
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
                "Dry-run: operação de configuração de rede validada; nenhuma consulta real foi realizada.",
                metadata,
            )
        if _network_backend is None:
            return self._failed(
                command.command_id,
                now_monotonic,
                "Backend seguro de configuração de rede indisponível.",
                metadata,
            )
        try:
            payload = self._collect_configuration(_network_backend)
            output, truncated = self._bounded_json(
                payload, contract.sandbox_policy.max_output_bytes
            )
        except Exception:
            return self._failed(
                command.command_id,
                now_monotonic,
                "Falha ao consultar configuração de rede.",
                metadata,
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

    def _collect_configuration(self, backend: object) -> dict[str, object]:
        addresses_by_name = backend.net_if_addrs()
        stats_by_name = backend.net_if_stats()
        if not isinstance(addresses_by_name, dict) or not isinstance(stats_by_name, dict):
            raise ValueError("invalid backend data")
        names = sorted(
            (name for name in addresses_by_name if isinstance(name, str) and name),
            key=str.casefold,
        )[: self.MAX_INTERFACES]
        interfaces: list[dict[str, object]] = []
        total_addresses = 0
        for name in names:
            stat = stats_by_name.get(name)
            is_up = getattr(stat, "isup", False)
            mtu = getattr(stat, "mtu", 0)
            if not isinstance(is_up, bool):
                is_up = False
            if not isinstance(mtu, int) or isinstance(mtu, bool) or mtu < 0:
                mtu = 0
            addresses: list[dict[str, str]] = []
            records = addresses_by_name.get(name, ())
            if not isinstance(records, (list, tuple)):
                records = ()
            for record in records:
                if total_addresses >= self.MAX_ADDRESSES:
                    break
                family = self._address_family(getattr(record, "family", None))
                address = getattr(record, "address", None)
                if family is None or not isinstance(address, str) or not address:
                    continue
                item = {
                    "address": address[: self.MAX_TEXT_LENGTH],
                    "address_family": family,
                }
                netmask = getattr(record, "netmask", None)
                if isinstance(netmask, str) and netmask:
                    item["netmask"] = netmask[: self.MAX_TEXT_LENGTH]
                addresses.append(item)
                total_addresses += 1
            addresses.sort(key=lambda item: (item["address_family"], item["address"]))
            interfaces.append(
                {
                    "addresses": addresses,
                    "interface_name": name[: self.MAX_TEXT_LENGTH],
                    "is_up": is_up,
                    "mtu": mtu,
                }
            )
        return {
            "address_count": total_addresses,
            "interface_count": len(interfaces),
            "interfaces": interfaces,
            "operation": "check_network_configuration",
        }

    @staticmethod
    def _address_family(value: object) -> str | None:
        name = getattr(value, "name", "")
        if name == "AF_INET":
            return "ipv4"
        if name == "AF_INET6":
            return "ipv6"
        number = getattr(value, "value", value)
        if number == 2:
            return "ipv4"
        if number in {10, 23}:
            return "ipv6"
        return None

    def _contract_error(self, contract: object, now_monotonic: object) -> str | None:
        if not isinstance(contract, LocalExecutionContract):
            return "Contrato local inválido."
        if not isinstance(now_monotonic, int | float) or isinstance(now_monotonic, bool) or now_monotonic < 0:
            return "Momento monotônico inválido."
        operation = contract.operation
        command = contract.command
        if operation.operation_name != "check_network_configuration" or command.operation_name != operation.operation_name:
            return "Operação local não suportada por este adapter."
        if operation.adapter_type != LocalAdapterType.NETWORK_DIAGNOSTIC or command.adapter_type != LocalAdapterType.NETWORK_DIAGNOSTIC:
            return "Adapter local incompatível."
        if operation.operation_type != LocalOperationType.READ_ONLY or command.operation_type != LocalOperationType.READ_ONLY:
            return "Tipo de operação incompatível."
        if command.target != ExecutionTarget.NETWORK or ExecutionTarget.NETWORK not in operation.allowed_targets:
            return "Target local incompatível."
        if command.risk != ExecutionRisk.LOW or ExecutionRisk.LOW not in operation.allowed_risks:
            return "Risco local incompatível."
        if contract.state != LocalExecutionState.PENDING:
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
        if operation.argument_names or command.arguments:
            return "Argumentos incompatíveis com consulta de configuração de rede."
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
                "authorization": RedactionReason.SECRET,
                "cookie": RedactionReason.SECRET,
            }[label]
            redactions.append(RedactedValue(f"{label}=[REDACTED]", reason))
            return f"{label}=[REDACTED]"

        return self._SECRET_PATTERN.sub(replace_secret, value), tuple(redactions)

    @classmethod
    def _bounded_json(cls, payload: dict[str, object], maximum_bytes: int) -> tuple[str, bool]:
        copied = {**payload, "interfaces": deepcopy_interfaces(payload.get("interfaces", []))}
        truncated = False
        while True:
            output = json.dumps(copied, sort_keys=True, separators=(",", ":"))
            if len(output.encode("utf-8")) <= maximum_bytes:
                return output, truncated
            if copied["interfaces"]:
                copied["interfaces"].pop()
                copied["interface_count"] = len(copied["interfaces"])
                copied["address_count"] = sum(
                    len(item.get("addresses", ())) for item in copied["interfaces"]
                )
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
        if isinstance(payload, dict) and isinstance(payload.get("interfaces"), list):
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


def deepcopy_interfaces(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [
        {**item, "addresses": [dict(address) for address in item.get("addresses", [])]}
        for item in value
        if isinstance(item, dict)
    ]
