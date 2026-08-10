"""Deny-by-default offline policy for future active network probes."""

import ipaddress
from dataclasses import dataclass

from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeBlockReason,
    NetworkProbeRequest,
    NetworkProbeTarget,
    NetworkProbeType,
    parse_host,
)


@dataclass(frozen=True)
class NetworkProbePolicy:
    enabled: bool = False
    allow_ping: bool = False
    allow_tcp_port_check: bool = False
    allow_real_probe: bool = False
    allow_ip_literals: bool = True
    allow_hostnames: bool = False
    allow_dns_resolution: bool = False
    allow_private_addresses: bool = False
    allow_loopback: bool = False
    allow_link_local: bool = False
    allow_multicast: bool = False
    allow_reserved: bool = False
    allow_unspecified: bool = False
    allow_broadcast: bool = False
    require_explicit_host_allowlist: bool = True
    require_explicit_port_allowlist: bool = True
    require_approval: bool = True
    require_valid_grant: bool = True
    require_session_match: bool = True
    max_attempts_per_probe: int = 1
    max_probes_per_session: int = 10
    default_timeout_ms: int = 3000
    max_timeout_ms: int = 5000
    allowed_hosts: tuple[str, ...] = ()
    allowed_ports: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        boolean_fields = (
            "enabled", "allow_ping", "allow_tcp_port_check", "allow_real_probe",
            "allow_ip_literals", "allow_hostnames", "allow_dns_resolution",
            "allow_private_addresses", "allow_loopback", "allow_link_local",
            "allow_multicast", "allow_reserved", "allow_unspecified", "allow_broadcast",
            "require_explicit_host_allowlist", "require_explicit_port_allowlist",
            "require_approval", "require_valid_grant", "require_session_match",
        )
        if any(not isinstance(getattr(self, name), bool) for name in boolean_fields):
            raise ValueError("policy flags must be boolean")
        for name in ("max_attempts_per_probe", "max_probes_per_session", "default_timeout_ms", "max_timeout_ms"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.default_timeout_ms > 3000 or self.max_timeout_ms > 5000:
            raise ValueError("network probe timeouts exceed conservative limits")
        if self.default_timeout_ms > self.max_timeout_ms:
            raise ValueError("default_timeout_ms must not exceed max_timeout_ms")
        if self.max_attempts_per_probe > 1:
            raise ValueError("automatic retries are not supported")
        if not isinstance(self.allowed_hosts, tuple) or not isinstance(self.allowed_ports, tuple):
            raise ValueError("allowlists must be tuples")
        normalized_hosts = tuple(parse_host(host)[0] for host in self.allowed_hosts)
        if len(set(normalized_hosts)) != len(normalized_hosts):
            raise ValueError("allowed_hosts must not contain duplicates")
        if any(not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535 for port in self.allowed_ports):
            raise ValueError("allowed_ports must contain valid integer ports")
        if len(set(self.allowed_ports)) != len(self.allowed_ports):
            raise ValueError("allowed_ports must not contain duplicates")
        object.__setattr__(self, "allowed_hosts", tuple(sorted(normalized_hosts)))
        object.__setattr__(self, "allowed_ports", tuple(sorted(self.allowed_ports)))

    def is_probe_type_allowed(self, probe_type: NetworkProbeType) -> bool:
        if not isinstance(probe_type, NetworkProbeType) or not self.enabled:
            return False
        return {
            NetworkProbeType.PING: self.allow_ping,
            NetworkProbeType.TCP_PORT_CHECK: self.allow_tcp_port_check,
        }[probe_type]

    def validate_target(self, target: NetworkProbeTarget) -> NetworkProbeBlockReason | None:
        if not isinstance(target, NetworkProbeTarget):
            return NetworkProbeBlockReason.INVALID_HOST
        try:
            normalized, parsed = parse_host(target.host)
        except ValueError:
            return NetworkProbeBlockReason.INVALID_HOST
        if parsed is None:
            if not self.allow_hostnames or not self.allow_dns_resolution:
                return NetworkProbeBlockReason.DNS_DISABLED
        else:
            if not self.allow_ip_literals:
                return NetworkProbeBlockReason.INVALID_HOST
            reason = self._special_address_reason(parsed)
            if reason is not None:
                return reason
        if self.require_explicit_host_allowlist and normalized not in self.allowed_hosts:
            return NetworkProbeBlockReason.HOST_NOT_ALLOWED
        return None

    def _special_address_reason(
        self, address: ipaddress.IPv4Address | ipaddress.IPv6Address
    ) -> NetworkProbeBlockReason | None:
        checks = (
            (address.is_unspecified, self.allow_unspecified, NetworkProbeBlockReason.UNSPECIFIED_ADDRESS_BLOCKED),
            (address.is_multicast, self.allow_multicast, NetworkProbeBlockReason.MULTICAST_BLOCKED),
            (address.is_loopback, self.allow_loopback, NetworkProbeBlockReason.LOOPBACK_BLOCKED),
            (address.is_link_local, self.allow_link_local, NetworkProbeBlockReason.LINK_LOCAL_BLOCKED),
            (
                address.is_reserved
                and not any((
                    address.is_loopback, address.is_link_local,
                    address.is_unspecified, address.is_multicast,
                )),
                self.allow_reserved,
                NetworkProbeBlockReason.RESERVED_BLOCKED,
            ),
            (
                address.is_private
                and not any((
                    address.is_loopback, address.is_link_local,
                    address.is_unspecified, address.is_reserved,
                )),
                self.allow_private_addresses,
                NetworkProbeBlockReason.HOST_NOT_ALLOWED,
            ),
        )
        return next((reason for present, allowed, reason in checks if present and not allowed), None)

    def is_host_allowed(self, host: str) -> bool:
        try:
            return self.validate_target(NetworkProbeTarget(host)) is None
        except ValueError:
            return False

    def is_port_allowed(self, port: object) -> bool:
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            return False
        return not self.require_explicit_port_allowlist or port in self.allowed_ports

    def validate_timeout(self, timeout_ms: object) -> bool:
        return (
            isinstance(timeout_ms, int) and not isinstance(timeout_ms, bool)
            and 0 < timeout_ms <= self.max_timeout_ms
        )

    def max_attempts_for_probe(self) -> int:
        return self.max_attempts_per_probe

    def can_execute_real_probe(
        self,
        request: NetworkProbeRequest,
        *,
        approval_granted: bool = False,
        grant_valid: bool = False,
        session_matches: bool = False,
    ) -> bool:
        if not isinstance(request, NetworkProbeRequest):
            return False
        if not self.enabled or not self.allow_real_probe or request.dry_run:
            return False
        if not self.is_probe_type_allowed(request.probe_type):
            return False
        if self.validate_target(request.target) is not None:
            return False
        if request.probe_type == NetworkProbeType.TCP_PORT_CHECK and not self.is_port_allowed(request.target.port):
            return False
        if not self.validate_timeout(request.timeout_ms) or request.attempt > self.max_attempts_per_probe:
            return False
        if self.require_approval and not approval_granted:
            return False
        if self.require_valid_grant and not grant_valid:
            return False
        if self.require_session_match and not session_matches:
            return False
        return True
