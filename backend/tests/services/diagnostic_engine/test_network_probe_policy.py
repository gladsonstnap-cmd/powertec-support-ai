import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    NetworkProbeBlockReason, NetworkProbePolicy, NetworkProbeRequest,
    NetworkProbeTarget, NetworkProbeType,
)


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
POLICY_FILE = ROOT / "app/services/diagnostic_engine/network_probe_policy.py"
MODELS_FILE = POLICY_FILE.with_name("network_probe_models.py")
PACKAGE_FILE = POLICY_FILE.with_name("__init__.py")


def request(probe_type=NetworkProbeType.PING, *, host="8.8.8.8", port=None,
            dry_run=False, timeout_ms=3000, attempt=1):
    return NetworkProbeRequest(
        probe_id="probe-1", session_id="session-1", request_id="request-1",
        action_id="action-1", grant_id="grant-1", probe_type=probe_type,
        target=NetworkProbeTarget(host, port), timeout_ms=timeout_ms, attempt=attempt,
        dry_run=dry_run, created_at_monotonic=1,
    )


def allowed_policy(probe_type=NetworkProbeType.PING, *, host="8.8.8.8", port=None, **changes):
    values = dict(
        enabled=True, allow_real_probe=True,
        allow_ping=probe_type == NetworkProbeType.PING,
        allow_tcp_port_check=probe_type == NetworkProbeType.TCP_PORT_CHECK,
        allowed_hosts=(host,), allowed_ports=() if port is None else (port,),
    )
    values.update(changes)
    return NetworkProbePolicy(**values)


@pytest.mark.parametrize("field,expected", [
    ("enabled", False), ("allow_ping", False), ("allow_tcp_port_check", False),
    ("allow_real_probe", False), ("allow_ip_literals", True),
    ("allow_hostnames", False), ("allow_dns_resolution", False),
    ("allow_private_addresses", False), ("allow_loopback", False),
    ("allow_link_local", False), ("allow_multicast", False),
    ("allow_reserved", False), ("allow_unspecified", False),
    ("allow_broadcast", False), ("require_explicit_host_allowlist", True),
    ("require_explicit_port_allowlist", True), ("require_approval", True),
    ("require_valid_grant", True), ("require_session_match", True),
    ("max_attempts_per_probe", 1), ("max_probes_per_session", 10),
    ("default_timeout_ms", 3000), ("max_timeout_ms", 5000),
    ("allowed_hosts", ()), ("allowed_ports", ()),
])
def test_default_policy_is_conservative(field, expected):
    assert getattr(NetworkProbePolicy(), field) == expected


def test_policy_is_frozen():
    with pytest.raises(FrozenInstanceError): NetworkProbePolicy().enabled = True


@pytest.mark.parametrize("field", [
    "enabled", "allow_ping", "allow_tcp_port_check", "allow_real_probe",
    "allow_ip_literals", "allow_hostnames", "allow_dns_resolution",
    "allow_private_addresses", "allow_loopback", "allow_link_local",
    "allow_multicast", "allow_reserved", "allow_unspecified", "allow_broadcast",
    "require_explicit_host_allowlist", "require_explicit_port_allowlist",
    "require_approval", "require_valid_grant", "require_session_match",
])
@pytest.mark.parametrize("value", [None, "true"])
def test_policy_flags_require_booleans(field, value):
    with pytest.raises(ValueError): NetworkProbePolicy(**{field: value})


@pytest.mark.parametrize("field,value", [
    ("max_attempts_per_probe", 0), ("max_attempts_per_probe", -1),
    ("max_attempts_per_probe", 2), ("max_attempts_per_probe", True),
    ("max_probes_per_session", 0), ("max_probes_per_session", -1),
    ("default_timeout_ms", 0), ("default_timeout_ms", 3001),
    ("default_timeout_ms", True), ("max_timeout_ms", 0),
    ("max_timeout_ms", 5001), ("max_timeout_ms", True),
])
def test_policy_rejects_unsafe_limits(field, value):
    with pytest.raises(ValueError): NetworkProbePolicy(**{field: value})


@pytest.mark.parametrize("hosts", [
    ["8.8.8.8"], {"8.8.8.8"}, "8.8.8.8", ("8.8.8.8", "8.8.8.8"),
    ("*",), ("*.local",), ("10.*",), ("10.0.0.0/8",),
    ("192.168.1.1-254",), ("host1,host2",), ("host1;host2",),
    ("host1 host2",),
])
def test_host_allowlist_must_be_exact_unique_tuple(hosts):
    with pytest.raises(ValueError): NetworkProbePolicy(allowed_hosts=hosts)


@pytest.mark.parametrize("ports", [
    [80], {80}, "80", (80, 80), (0,), (-1,), (65536,), (True,),
    ("80",), ("1-1024",), ((80, 443),),
])
def test_port_allowlist_must_be_exact_unique_integer_tuple(ports):
    with pytest.raises(ValueError): NetworkProbePolicy(allowed_ports=ports)


def test_allowlists_are_normalized_and_sorted():
    policy = NetworkProbePolicy(
        allowed_hosts=("2001:DB8::1", "8.8.8.8", "EXAMPLE.COM"),
        allowed_ports=(443, 22, 80),
    )
    assert policy.allowed_hosts == tuple(sorted(("2001:db8::1", "8.8.8.8", "example.com")))
    assert policy.allowed_ports == (22, 80, 443)


@pytest.mark.parametrize("probe_type,field", [
    (NetworkProbeType.PING, "allow_ping"),
    (NetworkProbeType.TCP_PORT_CHECK, "allow_tcp_port_check"),
])
def test_probe_type_requires_global_and_specific_enablement(probe_type, field):
    assert not NetworkProbePolicy().is_probe_type_allowed(probe_type)
    assert not NetworkProbePolicy(**{field: True}).is_probe_type_allowed(probe_type)
    assert NetworkProbePolicy(enabled=True, **{field: True}).is_probe_type_allowed(probe_type)


@pytest.mark.parametrize("invalid", [None, "PING", 1, object()])
def test_unknown_probe_types_are_blocked(invalid):
    assert not NetworkProbePolicy(enabled=True, allow_ping=True).is_probe_type_allowed(invalid)


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "9.9.9.9", "2001:4860:4860::8888"])
def test_exact_public_ip_allowlist(host):
    policy = NetworkProbePolicy(enabled=True, allowed_hosts=(host,))
    assert policy.is_host_allowed(host)
    assert not policy.is_host_allowed("8.8.4.4")


@pytest.mark.parametrize("host", [
    "10.0.0.1", "172.16.0.1", "192.168.1.1", "127.0.0.1", "::1",
    "169.254.1.1", "fe80::1", "224.0.0.1", "ff02::1", "0.0.0.0", "::",
    "240.0.0.1",
])
def test_special_and_private_addresses_are_not_implicitly_allowed(host):
    policy = NetworkProbePolicy(enabled=True, allowed_hosts=(host,))
    assert not policy.is_host_allowed(host)


@pytest.mark.parametrize("host,flag", [
    ("10.0.0.1", "allow_private_addresses"),
    ("127.0.0.1", "allow_loopback"), ("::1", "allow_loopback"),
    ("169.254.1.1", "allow_link_local"), ("fe80::1", "allow_link_local"),
    ("224.0.0.1", "allow_multicast"), ("ff02::1", "allow_multicast"),
    ("0.0.0.0", "allow_unspecified"), ("::", "allow_unspecified"),
    ("240.0.0.1", "allow_reserved"),
])
def test_special_address_needs_specific_flag_and_allowlist(host, flag):
    policy = NetworkProbePolicy(enabled=True, allowed_hosts=(host,), **{flag: True})
    assert policy.is_host_allowed(host)


@pytest.mark.parametrize("host", ["example.com", "host-1.local", "localhost"])
def test_hostname_requires_hostname_and_dns_flags_even_without_resolution(host):
    base = dict(enabled=True, allowed_hosts=(host,))
    assert not NetworkProbePolicy(**base).is_host_allowed(host)
    assert not NetworkProbePolicy(**base, allow_hostnames=True).is_host_allowed(host)
    assert NetworkProbePolicy(
        **base, allow_hostnames=True, allow_dns_resolution=True
    ).is_host_allowed(host)


@pytest.mark.parametrize("host", [
    "10.0.0.0/8", "192.168.1.0/24", "192.168.1.1-254", "host1,host2",
    "host1;host2", "host1 host2", "*", "*.local", "10.*",
])
def test_scan_syntax_is_never_interpreted(host):
    policy = NetworkProbePolicy(enabled=True)
    assert not policy.is_host_allowed(host)


@pytest.mark.parametrize("port", [1, 22, 53, 80, 443, 65535])
def test_exact_port_allowlist(port):
    policy = NetworkProbePolicy(allowed_ports=(port,))
    assert policy.is_port_allowed(port)
    assert not policy.is_port_allowed(8080 if port != 8080 else 8081)


@pytest.mark.parametrize("port", [0, -1, 65536, True, False, 1.5, "80", "1-1024", [80]])
def test_invalid_or_ranged_ports_are_blocked(port):
    assert not NetworkProbePolicy().is_port_allowed(port)


@pytest.mark.parametrize("timeout", [1, 100, 1000, 3000, 4999, 5000])
def test_timeout_within_bound_is_valid(timeout):
    assert NetworkProbePolicy().validate_timeout(timeout)


@pytest.mark.parametrize("timeout", [0, -1, 5001, True, False, 1.5, "3000", None])
def test_invalid_timeout_is_blocked(timeout):
    assert not NetworkProbePolicy().validate_timeout(timeout)


def test_attempt_limit_is_one_and_no_retry_is_automatic():
    policy = NetworkProbePolicy()
    assert policy.max_attempts_for_probe() == 1 and policy.max_probes_per_session == 10


@pytest.mark.parametrize("probe_type,port", [
    (NetworkProbeType.PING, None), (NetworkProbeType.TCP_PORT_CHECK, 443),
])
def test_fully_authorized_real_probe_is_only_structurally_represented(probe_type, port):
    policy = allowed_policy(probe_type, port=port)
    item = request(probe_type, port=port)
    assert policy.can_execute_real_probe(
        item, approval_granted=True, grant_valid=True, session_matches=True
    )


@pytest.mark.parametrize("field", [
    "enabled", "allow_real_probe", "allow_ping", "host", "approval", "grant", "session",
])
def test_real_probe_fails_closed_when_any_gate_is_missing(field):
    policy = allowed_policy()
    item = request()
    approval = grant = session = True
    if field in {"enabled", "allow_real_probe", "allow_ping"}:
        policy = replace(policy, **{field: False})
    elif field == "host":
        item = request(host="1.1.1.1")
    elif field == "approval": approval = False
    elif field == "grant": grant = False
    elif field == "session": session = False
    assert not policy.can_execute_real_probe(
        item, approval_granted=approval, grant_valid=grant, session_matches=session
    )


@pytest.mark.parametrize("dry_run", [True])
def test_dry_run_request_is_never_treated_as_real_execution(dry_run):
    policy = allowed_policy(); item = request(dry_run=dry_run)
    assert not policy.can_execute_real_probe(
        item, approval_granted=True, grant_valid=True, session_matches=True
    )


@pytest.mark.parametrize("name", ["socket", "subprocess", "requests", "httpx", "psutil", "urllib"])
def test_policy_has_no_network_or_process_imports(name):
    tree = ast.parse(POLICY_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "socket.", ".connect(", "connect_ex", ".send(", ".sendto(", ".recv(",
    "getaddrinfo", "gethostbyname", "subprocess", "powershell", "cmd.exe",
    "ping.exe", "test-netconnection", "netcat", "telnet", "curl ",
])
def test_policy_has_no_execution_or_command_capability(text):
    assert text not in POLICY_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("path", [POLICY_FILE, MODELS_FILE, PACKAGE_FILE, HERE])
def test_policy_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
