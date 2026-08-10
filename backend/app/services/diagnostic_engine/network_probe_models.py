"""Immutable offline-only models for future active network probes."""

import ipaddress
import re
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum


class NetworkProbeType(StrEnum):
    PING = "PING"
    TCP_PORT_CHECK = "TCP_PORT_CHECK"


class NetworkProbeState(StrEnum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    BLOCKED = "BLOCKED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


class NetworkProbeBlockReason(StrEnum):
    POLICY_DISABLED = "POLICY_DISABLED"
    INVALID_HOST = "INVALID_HOST"
    HOST_NOT_ALLOWED = "HOST_NOT_ALLOWED"
    INVALID_PORT = "INVALID_PORT"
    PORT_NOT_ALLOWED = "PORT_NOT_ALLOWED"
    BROADCAST_BLOCKED = "BROADCAST_BLOCKED"
    MULTICAST_BLOCKED = "MULTICAST_BLOCKED"
    UNSPECIFIED_ADDRESS_BLOCKED = "UNSPECIFIED_ADDRESS_BLOCKED"
    LOOPBACK_BLOCKED = "LOOPBACK_BLOCKED"
    LINK_LOCAL_BLOCKED = "LINK_LOCAL_BLOCKED"
    RESERVED_BLOCKED = "RESERVED_BLOCKED"
    CIDR_BLOCKED = "CIDR_BLOCKED"
    RANGE_BLOCKED = "RANGE_BLOCKED"
    DNS_DISABLED = "DNS_DISABLED"
    TIMEOUT_INVALID = "TIMEOUT_INVALID"
    TOO_MANY_ATTEMPTS = "TOO_MANY_ATTEMPTS"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    GRANT_INVALID = "GRANT_INVALID"
    SESSION_MISMATCH = "SESSION_MISMATCH"
    UNSUPPORTED_PROBE = "UNSUPPORTED_PROBE"
    VALIDATION_FAILED = "VALIDATION_FAILED"


_HOSTNAME = re.compile(
    r"(?=^.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*$"
)
_FORBIDDEN_HOST = re.compile(r"[\s,;*?\[\]/\\]")
_SENSITIVE = (
    "password", "senha", "token", "secret", "segredo", "credential", "credencial",
    "api_key", "authorization", "bearer", "cookie", "private_key",
)
_SCOPE_KEYS = (
    "host", "hosts", "port", "ports", "range", "cidr", "command", "script", "target",
)


def _nonempty(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a non-empty trimmed string")
    if len(value) > 128:
        raise ValueError(f"{name} is too long")
    return value


def _valid_port(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535


def parse_host(value: object) -> tuple[str, ipaddress.IPv4Address | ipaddress.IPv6Address | None]:
    host = _nonempty("host", value)
    if _FORBIDDEN_HOST.search(host) or ".." in host or "-" in host and re.search(r"\d-\d", host):
        raise ValueError("host must represent exactly one destination")
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        if not _HOSTNAME.fullmatch(host):
            raise ValueError("host format is invalid") from None
        return host.casefold(), None
    return parsed.compressed.casefold(), parsed


def _safe_metadata(value: object, key: str = "") -> object:
    normalized = key.strip().casefold()
    if any(term in normalized for term in (*_SENSITIVE, *_SCOPE_KEYS)):
        raise ValueError("metadata must not contain sensitive or scope-expanding data")
    if isinstance(value, dict):
        return {str(item_key): _safe_metadata(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return tuple(_safe_metadata(item) for item in value)
    if isinstance(value, str):
        lowered = value.casefold()
        if any(term in lowered for term in _SENSITIVE):
            raise ValueError("metadata must not contain sensitive data")
        if any(marker in value for marker in ("/", "*", ",", ";")):
            raise ValueError("metadata must not contain network scope expressions")
    return deepcopy(value)


@dataclass(frozen=True)
class NetworkProbeTarget:
    host: str
    port: int | None = None
    resolved_ip: str | None = None

    def __post_init__(self) -> None:
        normalized, _ = parse_host(self.host)
        if self.port is not None and not _valid_port(self.port):
            raise ValueError("port must be an integer from 1 through 65535")
        if self.resolved_ip is not None:
            raise ValueError("resolved_ip must remain None before execution")
        object.__setattr__(self, "host", normalized)


@dataclass(frozen=True)
class NetworkProbeRequest:
    probe_id: str
    session_id: str
    request_id: str
    action_id: str
    grant_id: str
    probe_type: NetworkProbeType
    target: NetworkProbeTarget
    timeout_ms: int = 3000
    attempt: int = 1
    dry_run: bool = True
    created_at_monotonic: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        for name in ("probe_id", "session_id", "request_id", "action_id", "grant_id"):
            _nonempty(name, getattr(self, name))
        if not isinstance(self.probe_type, NetworkProbeType):
            raise ValueError("probe_type must be a NetworkProbeType")
        if not isinstance(self.target, NetworkProbeTarget):
            raise ValueError("target must be a NetworkProbeTarget")
        if self.probe_type == NetworkProbeType.PING and self.target.port is not None:
            raise ValueError("PING must not include a port")
        if self.probe_type == NetworkProbeType.TCP_PORT_CHECK and self.target.port is None:
            raise ValueError("TCP_PORT_CHECK requires a port")
        if not isinstance(self.timeout_ms, int) or isinstance(self.timeout_ms, bool) or self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        if not isinstance(self.attempt, int) or isinstance(self.attempt, bool) or self.attempt <= 0:
            raise ValueError("attempt must be a positive integer")
        if not isinstance(self.dry_run, bool):
            raise ValueError("dry_run must be a boolean")
        if (
            not isinstance(self.created_at_monotonic, int | float)
            or isinstance(self.created_at_monotonic, bool)
            or self.created_at_monotonic < 0
        ):
            raise ValueError("created_at_monotonic must be non-negative")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dict")
        object.__setattr__(self, "target", deepcopy(self.target))
        object.__setattr__(self, "metadata", _safe_metadata(self.metadata))


@dataclass(frozen=True)
class NetworkProbeResult:
    probe_id: str
    state: NetworkProbeState
    success: bool = False
    block_reason: NetworkProbeBlockReason | None = None
    message: str = ""
    started_at_monotonic: float | None = None
    finished_at_monotonic: float | None = None
    latency_ms: float | None = None
    remote_ip: str | None = None
    remote_port: int | None = None
    metadata: dict[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _nonempty("probe_id", self.probe_id)
        if not isinstance(self.state, NetworkProbeState):
            raise ValueError("state must be a NetworkProbeState")
        if not isinstance(self.success, bool):
            raise ValueError("success must be a boolean")
        if self.block_reason is not None and not isinstance(self.block_reason, NetworkProbeBlockReason):
            raise ValueError("block_reason must be a NetworkProbeBlockReason or None")
        if not isinstance(self.message, str):
            raise ValueError("message must be a string")
        for name in ("started_at_monotonic", "finished_at_monotonic"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int | float) or isinstance(value, bool) or value < 0
            ):
                raise ValueError(f"{name} must be non-negative or None")
        if (
            self.started_at_monotonic is not None
            and self.finished_at_monotonic is not None
            and self.finished_at_monotonic < self.started_at_monotonic
        ):
            raise ValueError("finished_at_monotonic must not precede started_at_monotonic")
        if self.latency_ms is not None or self.remote_ip is not None:
            raise ValueError("unexecuted probe results must not claim latency or a remote IP")
        if self.remote_port is not None and not _valid_port(self.remote_port):
            raise ValueError("remote_port must be valid or None")
        if self.success and self.state != NetworkProbeState.SUCCESS:
            raise ValueError("success=True requires SUCCESS state")
        if self.state == NetworkProbeState.BLOCKED and self.block_reason is None:
            raise ValueError("BLOCKED state requires block_reason")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dict")
        object.__setattr__(self, "metadata", _safe_metadata(self.metadata))
