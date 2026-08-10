"""Immutable, privacy-bounded audit records for active network probes."""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum

from app.services.diagnostic_engine.network_probe_models import NetworkProbeType, parse_host


class NetworkProbeAuditEventType(StrEnum):
    REQUEST_CREATED = "REQUEST_CREATED"
    VALIDATION_PASSED = "VALIDATION_PASSED"
    VALIDATION_BLOCKED = "VALIDATION_BLOCKED"
    DISPATCH_REQUESTED = "DISPATCH_REQUESTED"
    DISPATCH_BLOCKED = "DISPATCH_BLOCKED"
    PROBE_STARTED = "PROBE_STARTED"
    PROBE_SUCCEEDED = "PROBE_SUCCEEDED"
    PROBE_FAILED = "PROBE_FAILED"
    PROBE_TIMED_OUT = "PROBE_TIMED_OUT"
    RATE_LIMITED = "RATE_LIMITED"
    COOLDOWN_BLOCKED = "COOLDOWN_BLOCKED"
    SESSION_LIMIT_REACHED = "SESSION_LIMIT_REACHED"
    DUPLICATE_BLOCKED = "DUPLICATE_BLOCKED"
    CANCELLED = "CANCELLED"


_SENSITIVE = (
    "password", "senha", "token", "secret", "segredo", "credential",
    "credencial", "api_key", "authorization", "bearer", "cookie", "private_key",
    "username", "environment", "command_line", "stack", "traceback",
)
_CONTROL_KEYS = {
    "host", "port", "limit", "cooldown", "policy", "probe_type", "counts",
    "max_probes_per_session", "max_probes_per_target", "minimum_interval_ms",
}


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a non-empty trimmed string")
    if len(value) > 256:
        raise ValueError(f"{name} is too long")
    return value


def _metadata(value: object, key: str = "") -> object:
    normalized = key.strip().casefold()
    if normalized in _CONTROL_KEYS or any(term in normalized for term in _SENSITIVE):
        raise ValueError("metadata must not contain sensitive or control data")
    if isinstance(value, dict):
        return {str(item_key): _metadata(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return tuple(_metadata(item) for item in value)
    if isinstance(value, str) and any(term in value.casefold() for term in _SENSITIVE):
        raise ValueError("metadata must not contain sensitive data")
    return deepcopy(value)


@dataclass(frozen=True)
class NetworkProbeAuditEvent:
    event_id: str
    probe_id: str
    session_id: str
    request_id: str
    action_id: str
    probe_type: NetworkProbeType
    host: str
    port: int | None
    event_type: NetworkProbeAuditEventType
    timestamp_monotonic: float
    message: str
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        for name in ("event_id", "probe_id", "session_id", "request_id", "action_id", "message"):
            _text(name, getattr(self, name))
        if not isinstance(self.probe_type, NetworkProbeType):
            raise ValueError("probe_type must be a NetworkProbeType")
        normalized_host, _ = parse_host(self.host)
        if self.port is not None and (
            not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535
        ):
            raise ValueError("port must be an integer from 1 through 65535 or None")
        if self.probe_type == NetworkProbeType.PING and self.port is not None:
            raise ValueError("PING audit events must not include a port")
        if not isinstance(self.event_type, NetworkProbeAuditEventType):
            raise ValueError("event_type must be a NetworkProbeAuditEventType")
        if (
            not isinstance(self.timestamp_monotonic, int | float)
            or isinstance(self.timestamp_monotonic, bool)
            or self.timestamp_monotonic < 0
        ):
            raise ValueError("timestamp_monotonic must be a non-negative number")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dict")
        object.__setattr__(self, "host", normalized_host)
        object.__setattr__(self, "metadata", _metadata(self.metadata))


@dataclass(frozen=True)
class NetworkProbeAuditTrail:
    session_id: str
    events: tuple[NetworkProbeAuditEvent, ...] = ()

    def __post_init__(self) -> None:
        _text("session_id", self.session_id)
        if not isinstance(self.events, tuple):
            raise ValueError("events must be a tuple")
        events = tuple(deepcopy(self.events))
        if any(not isinstance(item, NetworkProbeAuditEvent) for item in events):
            raise ValueError("events must contain NetworkProbeAuditEvent values")
        if any(item.session_id != self.session_id for item in events):
            raise ValueError("audit events must belong to the trail session")
        identifiers = tuple(item.event_id for item in events)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("audit event IDs must be unique")
        timestamps = tuple(item.timestamp_monotonic for item in events)
        if any(current < previous for previous, current in zip(timestamps, timestamps[1:])):
            raise ValueError("audit event timestamps must not regress")
        ordered = tuple(sorted(events, key=lambda item: (item.timestamp_monotonic, item.event_id)))
        object.__setattr__(self, "events", ordered)


def append_event(
    trail: NetworkProbeAuditTrail,
    event: NetworkProbeAuditEvent,
) -> NetworkProbeAuditTrail:
    if not isinstance(trail, NetworkProbeAuditTrail):
        raise ValueError("trail must be a NetworkProbeAuditTrail")
    if not isinstance(event, NetworkProbeAuditEvent):
        raise ValueError("event must be a NetworkProbeAuditEvent")
    return NetworkProbeAuditTrail(trail.session_id, (*trail.events, event))
