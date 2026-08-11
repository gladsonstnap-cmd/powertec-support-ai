"""Explicit, fail-closed activation for the native Windows ping backend."""

import sys
from dataclasses import dataclass, field

from app.services.diagnostic_engine.network_probe_models import NetworkProbeType
from app.services.diagnostic_engine.network_probe_policy import NetworkProbePolicy
from app.services.diagnostic_engine.safe_ping_backend import SafePingBackend


@dataclass(frozen=True)
class SafePingActivationPolicy:
    enabled: bool = False
    allow_native_windows_backend: bool = False
    max_timeout_ms: int = 2000
    max_attempts: int = 1
    require_explicit_real_execution: bool = True
    require_ip_literal: bool = True

    def __post_init__(self) -> None:
        for name in (
            "enabled",
            "allow_native_windows_backend",
            "require_explicit_real_execution",
            "require_ip_literal",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        if (
            not isinstance(self.max_timeout_ms, int)
            or isinstance(self.max_timeout_ms, bool)
            or not 1 <= self.max_timeout_ms <= 5000
        ):
            raise ValueError("max_timeout_ms must be an integer from 1 through 5000")
        if self.max_attempts != 1 or isinstance(self.max_attempts, bool):
            raise ValueError("max_attempts must be exactly 1")


@dataclass(frozen=True)
class SafePingBackendFactory:
    activation_policy: SafePingActivationPolicy = field(
        default_factory=SafePingActivationPolicy
    )

    def __post_init__(self) -> None:
        if self.activation_policy is None:
            object.__setattr__(self, "activation_policy", SafePingActivationPolicy())
        elif not isinstance(self.activation_policy, SafePingActivationPolicy):
            raise ValueError("activation_policy must be a SafePingActivationPolicy")

    def build(
        self,
        *,
        network_probe_policy: NetworkProbePolicy,
        explicit_real_execution: bool,
        probe_type: NetworkProbeType,
        timeout_ms: int,
        attempts: int,
    ) -> SafePingBackend | None:
        """Build an available backend without performing a probe."""
        activation = self.activation_policy
        try:
            if not all((
                activation.enabled,
                activation.allow_native_windows_backend,
                activation.require_explicit_real_execution,
                activation.require_ip_literal,
                isinstance(explicit_real_execution, bool) and explicit_real_execution,
                isinstance(network_probe_policy, NetworkProbePolicy),
                network_probe_policy.enabled,
                network_probe_policy.allow_ping,
                network_probe_policy.allow_real_probe,
                probe_type is NetworkProbeType.PING,
                sys.platform == "win32",
            )):
                return None
            if (
                not isinstance(timeout_ms, int)
                or isinstance(timeout_ms, bool)
                or timeout_ms <= 0
                or not network_probe_policy.validate_timeout(timeout_ms)
            ):
                return None
            if (
                not isinstance(attempts, int)
                or isinstance(attempts, bool)
                or attempts != 1
                or attempts > activation.max_attempts
                or attempts > network_probe_policy.max_attempts_per_probe
            ):
                return None
            effective_timeout = min(
                timeout_ms,
                network_probe_policy.max_timeout_ms,
                activation.max_timeout_ms,
                5000,
            )
            return SafePingBackend(max_timeout_ms=effective_timeout)
        except Exception:
            return None
