"""Closed, deterministic routing for explicitly authorized network probes."""

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeRequest,
    NetworkProbeResult,
    NetworkProbeType,
)
from app.services.diagnostic_engine.network_probe_policy import NetworkProbePolicy
from app.services.diagnostic_engine.safe_ping_adapter import SafePingAdapter
from app.services.diagnostic_engine.safe_ping_activation import SafePingBackendFactory


@dataclass(frozen=True)
class NetworkProbeDispatchResult:
    success: bool = False
    probe_type: NetworkProbeType | None = None
    result: NetworkProbeResult | None = None
    adapter_name: str | None = None
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise ValueError("success must be a boolean")
        if self.probe_type is not None and not isinstance(self.probe_type, NetworkProbeType):
            raise ValueError("probe_type must be a NetworkProbeType or None")
        if self.result is not None and not isinstance(self.result, NetworkProbeResult):
            raise ValueError("result must be a NetworkProbeResult or None")
        if self.success and self.result is None:
            raise ValueError("success=True requires a result")
        if self.result is not None and self.success != self.result.success:
            raise ValueError("dispatch success must match the probe result")
        if self.adapter_name is not None and (
            not isinstance(self.adapter_name, str) or not self.adapter_name.strip()
        ):
            raise ValueError("adapter_name must be non-empty or None")
        object.__setattr__(self, "result", deepcopy(self.result))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))


@dataclass(frozen=True)
class NetworkProbeDispatcher:
    policy: NetworkProbePolicy = field(default_factory=NetworkProbePolicy)
    ping_adapter: SafePingAdapter | None = None
    safe_ping_backend_factory: SafePingBackendFactory | None = None
    _registry: Mapping[NetworkProbeType, SafePingAdapter] = field(
        init=False, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        if self.policy is None:
            object.__setattr__(self, "policy", NetworkProbePolicy())
        elif not isinstance(self.policy, NetworkProbePolicy):
            raise ValueError("policy must be a NetworkProbePolicy")
        adapter = self.ping_adapter
        if adapter is None:
            adapter = SafePingAdapter(policy=self.policy)
            object.__setattr__(self, "ping_adapter", adapter)
        elif not isinstance(adapter, SafePingAdapter):
            raise ValueError("ping_adapter must be a SafePingAdapter")
        if adapter.policy != self.policy:
            raise ValueError("ping_adapter and dispatcher must use the same policy")
        if self.safe_ping_backend_factory is not None and not isinstance(
            self.safe_ping_backend_factory, SafePingBackendFactory
        ):
            raise ValueError("safe_ping_backend_factory must be a SafePingBackendFactory or None")
        object.__setattr__(
            self,
            "_registry",
            MappingProxyType({NetworkProbeType.PING: adapter}),
        )

    def supported_probe_types(self) -> tuple[NetworkProbeType, ...]:
        return tuple(sorted(self._registry, key=lambda item: item.value))

    def contains(self, probe_type: object) -> bool:
        return isinstance(probe_type, NetworkProbeType) and probe_type in self._registry

    def resolve(self, probe_type: object) -> SafePingAdapter | None:
        if not isinstance(probe_type, NetworkProbeType):
            return None
        return self._registry.get(probe_type)

    def dispatch(
        self,
        request: NetworkProbeRequest,
        now_monotonic: float,
    ) -> NetworkProbeDispatchResult:
        error = self._request_error(request, now_monotonic)
        probe_type = request.probe_type if isinstance(request, NetworkProbeRequest) else None
        if error is not None:
            return self._failure(error, probe_type)
        adapter = self.resolve(request.probe_type)
        if adapter is None:
            return self._failure("Tipo de probe não suportado.", request.probe_type)
        if (
            not request.dry_run
            and adapter.backend is None
            and self.safe_ping_backend_factory is not None
        ):
            try:
                backend = self.safe_ping_backend_factory.build(
                    network_probe_policy=self.policy,
                    explicit_real_execution=True,
                    probe_type=request.probe_type,
                    timeout_ms=request.timeout_ms,
                    attempts=request.attempt,
                )
                if backend is not None:
                    adapter = SafePingAdapter(policy=self.policy, backend=backend)
            except Exception:
                pass
        try:
            result = adapter.execute(request, now_monotonic)
        except Exception:
            return self._failure("Falha no probe de rede.", request.probe_type, type(adapter).__name__)
        if not isinstance(result, NetworkProbeResult) or result.probe_id != request.probe_id:
            return self._failure("Falha no probe de rede.", request.probe_type, type(adapter).__name__)
        return NetworkProbeDispatchResult(
            success=result.success,
            probe_type=request.probe_type,
            result=result,
            adapter_name=type(adapter).__name__,
            errors=() if result.success else ("O probe de rede retornou falha.",),
        )

    def _request_error(self, request: object, now: object) -> str | None:
        if not isinstance(request, NetworkProbeRequest):
            return "Request de probe de rede inválido."
        if not isinstance(now, int | float) or isinstance(now, bool) or now < 0:
            return "Momento monotônico inválido."
        if not self.contains(request.probe_type):
            return "Tipo de probe não suportado."
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (
                request.probe_id,
                request.session_id,
                request.request_id,
                request.action_id,
                request.grant_id,
            )
        ):
            return "Identificadores do probe são inválidos."
        if request.probe_type != NetworkProbeType.PING or request.target.port is not None:
            return "Tipo de probe não suportado."
        if not isinstance(request.dry_run, bool):
            return "Flag dry-run inválida."
        if not self.policy.validate_timeout(request.timeout_ms):
            return "Timeout do probe inválido."
        if (
            not isinstance(request.attempt, int)
            or isinstance(request.attempt, bool)
            or request.attempt != 1
            or request.attempt > self.policy.max_attempts_per_probe
        ):
            return "Tentativa do probe inválida."
        if not self.policy.is_probe_type_allowed(request.probe_type):
            return "Policy bloqueou o tipo de probe."
        if self.policy.validate_target(request.target) is not None:
            return "Policy bloqueou o target do probe."
        if not request.dry_run and not self.policy.can_execute_real_probe(
            request,
            approval_granted=True,
            grant_valid=True,
            session_matches=True,
        ):
            return "Policy bloqueou a execução real do probe."
        return None

    @staticmethod
    def _failure(
        error: str,
        probe_type: NetworkProbeType | None = None,
        adapter_name: str | None = None,
    ) -> NetworkProbeDispatchResult:
        return NetworkProbeDispatchResult(
            success=False,
            probe_type=probe_type,
            adapter_name=adapter_name,
            errors=(error,),
        )
