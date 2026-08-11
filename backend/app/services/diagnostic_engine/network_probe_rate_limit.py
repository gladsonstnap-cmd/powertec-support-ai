"""Offline, stateless rate-limit evaluation for active network probes."""

from dataclasses import dataclass, field, fields
from enum import StrEnum

from app.services.diagnostic_engine.network_probe_audit import (
    NetworkProbeAuditEventType,
    NetworkProbeAuditTrail,
)
from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeRequest,
    NetworkProbeResult,
    NetworkProbeState,
)


class NetworkProbeRateLimitBlockReason(StrEnum):
    SESSION_LIMIT_REACHED = "SESSION_LIMIT_REACHED"
    TARGET_LIMIT_REACHED = "TARGET_LIMIT_REACHED"
    GLOBAL_COOLDOWN = "GLOBAL_COOLDOWN"
    TARGET_COOLDOWN = "TARGET_COOLDOWN"
    DUPLICATE_PENDING_REQUEST = "DUPLICATE_PENDING_REQUEST"
    DUPLICATE_INFLIGHT_PROBE = "DUPLICATE_INFLIGHT_PROBE"
    INVALID_HISTORY = "INVALID_HISTORY"
    POLICY_DISABLED = "POLICY_DISABLED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


@dataclass(frozen=True)
class NetworkProbeRateLimitPolicy:
    enabled: bool = True
    max_probes_per_session: int = 10
    max_probes_per_target: int = 3
    minimum_interval_ms: int = 1000
    minimum_same_target_interval_ms: int = 3000
    block_duplicate_pending_request: bool = True
    block_duplicate_inflight_probe: bool = True
    count_dry_runs: bool = True
    count_failed_probes: bool = True
    count_timeouts: bool = True
    count_blocked_attempts: bool = False
    fail_closed: bool = True

    def __post_init__(self) -> None:
        integer_fields = {
            "max_probes_per_session", "max_probes_per_target",
            "minimum_interval_ms", "minimum_same_target_interval_ms",
        }
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name in integer_fields:
                minimum = 1 if item.name.startswith("max_") else 0
                if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                    raise ValueError(f"{item.name} must be an integer of at least {minimum}")
            elif not isinstance(value, bool):
                raise ValueError(f"{item.name} must be a boolean")
        if self.minimum_same_target_interval_ms < self.minimum_interval_ms:
            raise ValueError("same-target cooldown must not be shorter than global cooldown")


@dataclass(frozen=True)
class NetworkProbeRateLimitResult:
    allowed: bool
    block_reason: NetworkProbeRateLimitBlockReason | None = None
    message: str = ""
    next_allowed_at_monotonic: float | None = None
    current_session_count: int = 0
    current_target_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise ValueError("allowed must be a boolean")
        if self.allowed and self.block_reason is not None:
            raise ValueError("an allowed result must not have a block reason")
        if not self.allowed and not isinstance(self.block_reason, NetworkProbeRateLimitBlockReason):
            raise ValueError("a blocked result requires a block reason")
        if not isinstance(self.message, str):
            raise ValueError("message must be a string")
        if self.next_allowed_at_monotonic is not None and (
            not isinstance(self.next_allowed_at_monotonic, int | float)
            or isinstance(self.next_allowed_at_monotonic, bool)
            or self.next_allowed_at_monotonic < 0
        ):
            raise ValueError("next_allowed_at_monotonic must be non-negative or None")
        for name in ("current_session_count", "current_target_count"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class NetworkProbeRateLimiter:
    policy: NetworkProbeRateLimitPolicy = field(default_factory=NetworkProbeRateLimitPolicy)

    def __post_init__(self) -> None:
        if self.policy is None:
            object.__setattr__(self, "policy", NetworkProbeRateLimitPolicy())
        elif not isinstance(self.policy, NetworkProbeRateLimitPolicy):
            raise ValueError("policy must be a NetworkProbeRateLimitPolicy")

    def evaluate(
        self,
        *,
        request: NetworkProbeRequest,
        existing_requests: tuple[NetworkProbeRequest, ...] = (),
        existing_results: tuple[NetworkProbeResult, ...] = (),
        audit_trail: NetworkProbeAuditTrail | None = None,
        now_monotonic: float,
    ) -> NetworkProbeRateLimitResult:
        if not self.policy.enabled:
            return self._blocked(NetworkProbeRateLimitBlockReason.POLICY_DISABLED, "Rate limiting está desabilitado.")
        history_error = self._history_error(
            request, existing_requests, existing_results, audit_trail, now_monotonic
        )
        if history_error is not None:
            if self.policy.fail_closed:
                return self._blocked(
                    NetworkProbeRateLimitBlockReason.INVALID_HISTORY,
                    "Histórico de probes inválido.",
                )
            existing_requests, existing_results, audit_trail = (), (), None

        results_by_probe = {item.probe_id: item for item in existing_results}
        counted_requests = tuple(
            item for item in existing_requests
            if item.session_id == request.session_id and self._counts(item, results_by_probe.get(item.probe_id))
        )
        blocked_probe_ids = self._counted_blocked_probe_ids(audit_trail, counted_requests)
        session_count = len(counted_requests) + len(blocked_probe_ids)
        target_key = self._target_key(request)
        target_count = sum(self._target_key(item) == target_key for item in counted_requests)
        if audit_trail is not None and self.policy.count_blocked_attempts:
            target_count += len({
                item.probe_id for item in audit_trail.events
                if item.probe_id in blocked_probe_ids and (item.host, item.port) == target_key
            })

        if session_count >= self.policy.max_probes_per_session:
            return self._blocked(
                NetworkProbeRateLimitBlockReason.SESSION_LIMIT_REACHED,
                "Limite de probes da sessão atingido.", session_count, target_count,
            )
        if target_count >= self.policy.max_probes_per_target:
            return self._blocked(
                NetworkProbeRateLimitBlockReason.TARGET_LIMIT_REACHED,
                "Limite de probes para o destino atingido.", session_count, target_count,
            )

        equivalent = tuple(item for item in existing_requests if self._equivalent(item, request))
        pending = tuple(item for item in equivalent if item.probe_id not in results_by_probe)
        if pending and self.policy.block_duplicate_pending_request:
            return self._blocked(
                NetworkProbeRateLimitBlockReason.DUPLICATE_PENDING_REQUEST,
                "Request equivalente já está pendente.", session_count, target_count,
            )
        inflight_states = {NetworkProbeState.PENDING, NetworkProbeState.VALIDATED}
        if self.policy.block_duplicate_inflight_probe and any(
            results_by_probe.get(item.probe_id) is not None
            and results_by_probe[item.probe_id].state in inflight_states
            for item in equivalent
        ):
            return self._blocked(
                NetworkProbeRateLimitBlockReason.DUPLICATE_INFLIGHT_PROBE,
                "Probe equivalente já está em andamento.", session_count, target_count,
            )

        target_last = self._latest_timestamp(request, counted_requests, existing_results, audit_trail, same_target=True)
        if target_last is not None:
            next_target = target_last + self.policy.minimum_same_target_interval_ms / 1000
            if now_monotonic < next_target:
                return self._blocked(
                    NetworkProbeRateLimitBlockReason.TARGET_COOLDOWN,
                    "Cooldown do destino ainda ativo.", session_count, target_count, next_target,
                )
        global_last = self._latest_timestamp(request, counted_requests, existing_results, audit_trail, same_target=False)
        if global_last is not None:
            next_global = global_last + self.policy.minimum_interval_ms / 1000
            if now_monotonic < next_global:
                return self._blocked(
                    NetworkProbeRateLimitBlockReason.GLOBAL_COOLDOWN,
                    "Cooldown global de probes ainda ativo.", session_count, target_count, next_global,
                )
        return NetworkProbeRateLimitResult(
            allowed=True,
            message="Probe permitido pelos limites estruturais.",
            current_session_count=session_count,
            current_target_count=target_count,
        )

    def _history_error(self, request, requests, results, trail, now) -> str | None:
        if not isinstance(request, NetworkProbeRequest):
            return "invalid request"
        if not isinstance(requests, tuple) or any(not isinstance(item, NetworkProbeRequest) for item in requests):
            return "invalid requests"
        if not isinstance(results, tuple) or any(not isinstance(item, NetworkProbeResult) for item in results):
            return "invalid results"
        if trail is not None and not isinstance(trail, NetworkProbeAuditTrail):
            return "invalid trail"
        if not isinstance(now, int | float) or isinstance(now, bool) or now < 0:
            return "invalid time"
        if trail is not None and trail.session_id != request.session_id:
            return "session mismatch"
        relevant = tuple(item for item in requests if item.session_id == request.session_id)
        probe_ids = tuple(item.probe_id for item in relevant)
        request_ids = tuple(item.request_id for item in relevant)
        if len(set(probe_ids)) != len(probe_ids) or len(set(request_ids)) != len(request_ids):
            return "duplicate request identifiers"
        result_ids = tuple(item.probe_id for item in results)
        if len(set(result_ids)) != len(result_ids):
            return "duplicate result identifiers"
        all_probe_ids = {item.probe_id for item in requests}
        if any(item.probe_id not in all_probe_ids for item in results):
            return "orphan result"
        timestamps = tuple(item.created_at_monotonic for item in relevant)
        if any(current < previous for previous, current in zip(timestamps, timestamps[1:])):
            return "regressive request timestamps"
        if any(timestamp > now for timestamp in timestamps):
            return "future request timestamp"
        request_by_probe = {item.probe_id: item for item in requests}
        for item in results:
            source = request_by_probe[item.probe_id]
            result_times = tuple(
                value for value in (item.started_at_monotonic, item.finished_at_monotonic)
                if value is not None
            )
            if any(value < source.created_at_monotonic or value > now for value in result_times):
                return "inconsistent result timestamp"
        if trail is not None and any(item.timestamp_monotonic > now for item in trail.events):
            return "future audit timestamp"
        return None

    def _counts(self, request: NetworkProbeRequest, result: NetworkProbeResult | None) -> bool:
        if request.dry_run and not self.policy.count_dry_runs:
            return False
        if result is None or result.state in {NetworkProbeState.PENDING, NetworkProbeState.VALIDATED, NetworkProbeState.SUCCESS}:
            return True
        if result.state == NetworkProbeState.FAILED:
            return self.policy.count_failed_probes
        if result.state == NetworkProbeState.TIMED_OUT:
            return self.policy.count_timeouts
        if result.state == NetworkProbeState.BLOCKED:
            return self.policy.count_blocked_attempts
        return False

    def _counted_blocked_probe_ids(self, trail, counted_requests) -> set[str]:
        if trail is None or not self.policy.count_blocked_attempts:
            return set()
        represented = {item.probe_id for item in counted_requests}
        blocked_types = {
            NetworkProbeAuditEventType.VALIDATION_BLOCKED,
            NetworkProbeAuditEventType.DISPATCH_BLOCKED,
            NetworkProbeAuditEventType.RATE_LIMITED,
            NetworkProbeAuditEventType.COOLDOWN_BLOCKED,
            NetworkProbeAuditEventType.SESSION_LIMIT_REACHED,
            NetworkProbeAuditEventType.DUPLICATE_BLOCKED,
        }
        return {
            item.probe_id for item in trail.events
            if item.event_type in blocked_types and item.probe_id not in represented
        }

    @staticmethod
    def _target_key(request: NetworkProbeRequest) -> tuple[str, int | None]:
        return request.target.host, request.target.port

    @staticmethod
    def _equivalent(left: NetworkProbeRequest, right: NetworkProbeRequest) -> bool:
        return (
            left.session_id == right.session_id
            and left.probe_type == right.probe_type
            and left.target == right.target
            and left.action_id == right.action_id
            and left.grant_id == right.grant_id
            and left.dry_run == right.dry_run
        )

    def _latest_timestamp(self, request, requests, results, trail, *, same_target):
        request_by_probe = {item.probe_id: item for item in requests}
        target = self._target_key(request)
        timestamps = [
            item.created_at_monotonic for item in requests
            if not same_target or self._target_key(item) == target
        ]
        for result in results:
            source = request_by_probe.get(result.probe_id)
            if source is None or same_target and self._target_key(source) != target:
                continue
            for value in (result.started_at_monotonic, result.finished_at_monotonic):
                if value is not None:
                    timestamps.append(value)
        if trail is not None:
            timestamps.extend(
                item.timestamp_monotonic for item in trail.events
                if item.probe_id != request.probe_id
                and self._audit_event_counts(item.event_type)
                and (not same_target or (item.host, item.port) == target)
            )
        return max(timestamps, default=None)

    def _audit_event_counts(self, event_type: NetworkProbeAuditEventType) -> bool:
        blocked_types = {
            NetworkProbeAuditEventType.VALIDATION_BLOCKED,
            NetworkProbeAuditEventType.DISPATCH_BLOCKED,
            NetworkProbeAuditEventType.RATE_LIMITED,
            NetworkProbeAuditEventType.COOLDOWN_BLOCKED,
            NetworkProbeAuditEventType.SESSION_LIMIT_REACHED,
            NetworkProbeAuditEventType.DUPLICATE_BLOCKED,
        }
        return self.policy.count_blocked_attempts or event_type not in blocked_types

    @staticmethod
    def _blocked(reason, message, session_count=0, target_count=0, next_allowed=None):
        return NetworkProbeRateLimitResult(
            allowed=False,
            block_reason=reason,
            message=message,
            next_allowed_at_monotonic=next_allowed,
            current_session_count=session_count,
            current_target_count=target_count,
        )
