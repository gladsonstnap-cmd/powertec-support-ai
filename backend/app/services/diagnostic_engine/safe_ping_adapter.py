"""Single-host ping adapter with an injected, fail-closed backend.

The default adapter performs no network activity.  Real traffic is possible only
through an explicitly supplied backend after the request passes every policy gate.
"""

import ipaddress
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeBlockReason,
    NetworkProbeRequest,
    NetworkProbeResult,
    NetworkProbeState,
    NetworkProbeType,
    parse_host,
)
from app.services.diagnostic_engine.network_probe_policy import NetworkProbePolicy


@dataclass(frozen=True)
class PingBackendResult:
    success: bool = False
    timed_out: bool = False
    latency_ms: float | None = None
    remote_ip: str | None = None
    unavailable: bool = False

    def __post_init__(self) -> None:
        if not all(isinstance(value, bool) for value in (self.success, self.timed_out, self.unavailable)):
            raise ValueError("backend result flags must be boolean")
        if sum((self.success, self.timed_out, self.unavailable)) > 1:
            raise ValueError("backend result states are mutually exclusive")
        if self.latency_ms is not None and (
            not isinstance(self.latency_ms, int | float)
            or isinstance(self.latency_ms, bool)
            or self.latency_ms < 0
        ):
            raise ValueError("latency_ms must be non-negative or None")
        if not self.success and self.latency_ms is not None:
            raise ValueError("a failed ping must not report latency")
        if self.remote_ip is not None:
            try:
                normalized = ipaddress.ip_address(self.remote_ip).compressed.casefold()
            except ValueError:
                raise ValueError("remote_ip must be an IP literal or None") from None
            if not self.success:
                raise ValueError("a failed ping must not report remote_ip")
            object.__setattr__(self, "remote_ip", normalized)


@runtime_checkable
class PingBackendProtocol(Protocol):
    def ping(self, *, host: str, timeout_ms: int) -> PingBackendResult: ...


@dataclass(frozen=True)
class SafePingAdapter:
    policy: NetworkProbePolicy = field(default_factory=NetworkProbePolicy)
    backend: PingBackendProtocol | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.policy is None:
            object.__setattr__(self, "policy", NetworkProbePolicy())
        elif not isinstance(self.policy, NetworkProbePolicy):
            raise ValueError("policy must be a NetworkProbePolicy")
        if self.backend is not None and not isinstance(self.backend, PingBackendProtocol):
            raise ValueError("backend must implement PingBackendProtocol")

    def execute(
        self,
        request: NetworkProbeRequest,
        now_monotonic: float,
    ) -> NetworkProbeResult:
        probe_id = getattr(request, "probe_id", "invalid-probe")
        if not isinstance(probe_id, str) or not probe_id.strip():
            probe_id = "invalid-probe"
        error = self._request_error(request, now_monotonic)
        if error is not None:
            return self._result(probe_id, NetworkProbeState.BLOCKED, error, now_monotonic)

        if request.dry_run:
            return self._result(
                request.probe_id,
                NetworkProbeState.SUCCESS,
                "Dry-run: ping validado; nenhum pacote foi enviado.",
                now_monotonic,
                success=True,
            )

        _, parsed = parse_host(request.target.host)
        if parsed is None:
            return self._result(
                request.probe_id,
                NetworkProbeState.BLOCKED,
                "Execução real exige IP literal explicitamente autorizado.",
                now_monotonic,
            )
        if not self.policy.can_execute_real_probe(
            request,
            approval_granted=True,
            grant_valid=True,
            session_matches=True,
        ):
            return self._result(
                request.probe_id,
                NetworkProbeState.BLOCKED,
                "A policy bloqueia a execução real de ping.",
                now_monotonic,
            )
        if self.backend is None:
            return self._result(
                request.probe_id,
                NetworkProbeState.FAILED,
                "Backend seguro de ping indisponível.",
                now_monotonic,
            )
        try:
            backend_result = self.backend.ping(
                host=request.target.host,
                timeout_ms=request.timeout_ms,
            )
            if not isinstance(backend_result, PingBackendResult):
                raise ValueError("invalid backend result")
        except Exception:
            return self._result(
                request.probe_id,
                NetworkProbeState.FAILED,
                "Falha ao executar ping.",
                now_monotonic,
            )
        if backend_result.unavailable:
            return self._result(
                request.probe_id,
                NetworkProbeState.FAILED,
                "Backend seguro de ping indisponível.",
                now_monotonic,
            )
        if backend_result.timed_out:
            return self._result(
                request.probe_id,
                NetworkProbeState.TIMED_OUT,
                "Tempo limite excedido ao executar ping.",
                now_monotonic,
            )
        if not backend_result.success:
            return self._result(
                request.probe_id,
                NetworkProbeState.FAILED,
                "Host não respondeu ao ping.",
                now_monotonic,
            )
        return self._result(
            request.probe_id,
            NetworkProbeState.SUCCESS,
            "Host respondeu ao ping.",
            now_monotonic,
            success=True,
        )

    def _request_error(self, request: object, now: object) -> str | None:
        if not isinstance(request, NetworkProbeRequest):
            return "Request de ping inválido."
        if not isinstance(now, int | float) or isinstance(now, bool) or now < 0:
            return "Momento monotônico inválido."
        if request.probe_type != NetworkProbeType.PING:
            return "Somente PING é suportado por este adapter."
        if request.target.port is not None:
            return "PING não aceita porta."
        if request.attempt != 1 or request.attempt > self.policy.max_attempts_per_probe:
            return "Somente uma tentativa de ping é permitida."
        if not self.policy.validate_timeout(request.timeout_ms):
            return "Timeout de ping inválido."
        if not self.policy.enabled or not self.policy.is_probe_type_allowed(NetworkProbeType.PING):
            return "A policy bloqueia ping."
        try:
            normalized, parsed = parse_host(request.target.host)
        except (TypeError, ValueError):
            return "Host de ping inválido."
        if (
            isinstance(parsed, ipaddress.IPv4Address)
            and parsed == ipaddress.IPv4Address("255.255.255.255")
            and not self.policy.allow_broadcast
        ):
            return "Broadcast está bloqueado pela policy."
        if not self.policy.is_host_allowed(normalized):
            return "Host não autorizado pela policy."
        return None

    @staticmethod
    def _result(
        probe_id: str,
        state: NetworkProbeState,
        message: str,
        now: object,
        *,
        success: bool = False,
    ) -> NetworkProbeResult:
        timestamp = (
            float(now)
            if isinstance(now, int | float) and not isinstance(now, bool) and now >= 0
            else None
        )
        return NetworkProbeResult(
            probe_id=probe_id,
            state=state,
            success=success,
            block_reason=(
                NetworkProbeBlockReason.VALIDATION_FAILED
                if state == NetworkProbeState.BLOCKED
                else None
            ),
            message=message,
            started_at_monotonic=timestamp,
            finished_at_monotonic=timestamp,
            latency_ms=None,
            remote_ip=None,
            remote_port=None,
            metadata={"adapter": "safe_ping", "raw_output_preserved": False},
        )
