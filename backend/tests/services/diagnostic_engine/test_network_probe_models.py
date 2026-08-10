import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    NetworkProbeBlockReason, NetworkProbeRequest, NetworkProbeResult,
    NetworkProbeState, NetworkProbeTarget, NetworkProbeType,
)


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
MODELS_FILE = ROOT / "app/services/diagnostic_engine/network_probe_models.py"
PACKAGE_FILE = MODELS_FILE.with_name("__init__.py")


def request(probe_type=NetworkProbeType.PING, *, host="8.8.8.8", port=None, **changes):
    values = dict(
        probe_id="probe-1", session_id="session-1", request_id="request-1",
        action_id="action-1", grant_id="grant-1", probe_type=probe_type,
        target=NetworkProbeTarget(host, port), timeout_ms=3000, attempt=1,
        dry_run=True, created_at_monotonic=10, metadata={"safe": ["value"]},
    )
    values.update(changes)
    return NetworkProbeRequest(**values)


@pytest.mark.parametrize("enum_type,member,value", [
    (NetworkProbeType, NetworkProbeType.PING, "PING"),
    (NetworkProbeType, NetworkProbeType.TCP_PORT_CHECK, "TCP_PORT_CHECK"),
    *[(NetworkProbeState, member, member.name) for member in NetworkProbeState],
    *[(NetworkProbeBlockReason, member, member.name) for member in NetworkProbeBlockReason],
])
def test_enums_have_stable_string_values(enum_type, member, value):
    assert isinstance(member, enum_type) and member.value == value


@pytest.mark.parametrize("host,normalized", [
    ("8.8.8.8", "8.8.8.8"), ("1.1.1.1", "1.1.1.1"),
    ("2001:db8::1", "2001:db8::1"), ("FE80::1", "fe80::1"),
    ("example.com", "example.com"), ("HOST-1.LOCAL", "host-1.local"),
    ("localhost", "localhost"), ("a.b", "a.b"),
])
def test_target_accepts_one_structural_destination(host, normalized):
    target = NetworkProbeTarget(host)
    assert target.host == normalized and target.port is None and target.resolved_ip is None


@pytest.mark.parametrize("host", [
    "", " ", " host", "host ", "host1,host2", "host1;host2", "host1 host2",
    "192.168.1.0/24", "10.0.0.0/8", "192.168.1.1-254", "10.0.0.1-10",
    "*", "*.local", "192.168.*", "host?", "host[1]", "../host", "host\\name",
    ".host", "host.", "host..name", "-host", "host-", "a" * 254,
])
def test_target_blocks_scan_and_malformed_host_syntax(host):
    with pytest.raises(ValueError):
        NetworkProbeTarget(host)


@pytest.mark.parametrize("port", [1, 22, 53, 80, 443, 65535])
def test_target_accepts_valid_single_ports(port):
    assert NetworkProbeTarget("8.8.8.8", port).port == port


@pytest.mark.parametrize("port", [0, -1, 65536, True, False, 1.0, "80", "1-1024", [80], (80,)])
def test_target_rejects_invalid_or_ranged_ports(port):
    with pytest.raises(ValueError):
        NetworkProbeTarget("8.8.8.8", port)


@pytest.mark.parametrize("resolved", ["8.8.8.8", "2001:db8::1", "hostname", ""])
def test_target_never_accepts_pre_resolved_ip(resolved):
    with pytest.raises(ValueError, match="resolved_ip"):
        NetworkProbeTarget("8.8.8.8", resolved_ip=resolved)


def test_target_and_request_are_frozen():
    target = NetworkProbeTarget("8.8.8.8")
    item = request()
    with pytest.raises(FrozenInstanceError): target.host = "1.1.1.1"
    with pytest.raises(FrozenInstanceError): item.dry_run = False


@pytest.mark.parametrize("probe_type,port", [
    (NetworkProbeType.PING, None),
    (NetworkProbeType.TCP_PORT_CHECK, 22),
    (NetworkProbeType.TCP_PORT_CHECK, 443),
])
@pytest.mark.parametrize("dry_run", [True, False])
def test_request_represents_ping_or_tcp_intent_without_execution(probe_type, port, dry_run):
    item = request(probe_type, port=port, dry_run=dry_run)
    assert item.probe_type == probe_type and item.target.port == port
    assert item.dry_run is dry_run and item.target.resolved_ip is None


@pytest.mark.parametrize("probe_type,port", [
    (NetworkProbeType.PING, 80), (NetworkProbeType.PING, 1),
    (NetworkProbeType.TCP_PORT_CHECK, None),
])
def test_request_enforces_probe_specific_port_shape(probe_type, port):
    with pytest.raises(ValueError):
        request(probe_type, port=port)


@pytest.mark.parametrize("field", ["probe_id", "session_id", "request_id", "action_id", "grant_id"])
@pytest.mark.parametrize("value", [None, "", " leading", "trailing "])
def test_request_rejects_invalid_identifiers(field, value):
    with pytest.raises(ValueError):
        request(**{field: value})


@pytest.mark.parametrize("timeout", [0, -1, True, False, 1.5, "3000", None])
def test_request_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError): request(timeout_ms=timeout)


@pytest.mark.parametrize("attempt", [0, -1, True, False, 1.5, "1", None])
def test_request_rejects_invalid_attempt(attempt):
    with pytest.raises(ValueError): request(attempt=attempt)


@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_request_requires_boolean_dry_run(value):
    with pytest.raises(ValueError): request(dry_run=value)


@pytest.mark.parametrize("value", [-1, True, "10", None, object()])
def test_request_rejects_invalid_timestamp(value):
    with pytest.raises(ValueError): request(created_at_monotonic=value)


@pytest.mark.parametrize("metadata", [
    {"password": "x"}, {"token": "x"}, {"secret": "x"}, {"api_key": "x"},
    {"authorization": "x"}, {"cookie": "x"}, {"private_key": "x"},
    {"safe": {"credential": "x"}}, {"host": "8.8.8.8"}, {"hosts": ["a", "b"]},
    {"port": 80}, {"ports": [80]}, {"range": "1-10"}, {"cidr": "10.0.0.0/8"},
    {"command": "ping"}, {"script": "x"}, {"target": "x"},
    {"safe": "password=x"}, {"safe": "10.0.0.0/8"}, {"safe": "a,b"},
])
def test_request_metadata_cannot_leak_secrets_or_expand_scope(metadata):
    with pytest.raises(ValueError): request(metadata=metadata)


def test_request_metadata_is_defensively_copied():
    metadata = {"safe": ["value"]}; item = request(metadata=metadata)
    metadata["safe"].append("changed")
    assert item.metadata == {"safe": ("value",)}


@pytest.mark.parametrize("state", list(NetworkProbeState))
def test_result_represents_structural_states_without_network_claims(state):
    reason = NetworkProbeBlockReason.POLICY_DISABLED if state == NetworkProbeState.BLOCKED else None
    result = NetworkProbeResult("probe-1", state, block_reason=reason)
    assert result.latency_ms is None and result.remote_ip is None


@pytest.mark.parametrize("field,value", [
    ("latency_ms", 1), ("latency_ms", 0.0), ("remote_ip", "8.8.8.8"),
    ("remote_ip", "2001:db8::1"),
])
def test_result_cannot_pretend_a_probe_was_executed(field, value):
    with pytest.raises(ValueError): NetworkProbeResult("probe-1", NetworkProbeState.PENDING, **{field: value})


@pytest.mark.parametrize("port", [0, -1, 65536, True, "80"])
def test_result_rejects_invalid_remote_port(port):
    with pytest.raises(ValueError): NetworkProbeResult("probe-1", NetworkProbeState.FAILED, remote_port=port)


def test_blocked_result_requires_reason_and_success_requires_success_state():
    with pytest.raises(ValueError): NetworkProbeResult("probe-1", NetworkProbeState.BLOCKED)
    with pytest.raises(ValueError): NetworkProbeResult("probe-1", NetworkProbeState.FAILED, success=True)


@pytest.mark.parametrize("name", ["socket", "subprocess", "requests", "httpx", "psutil", "urllib"])
def test_models_have_no_network_or_process_imports(name):
    tree = ast.parse(MODELS_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "socket.", ".connect(", "connect_ex", ".send(", ".sendto(", ".recv(",
    "getaddrinfo", "gethostbyname", "subprocess", "powershell", "cmd.exe",
    "ping.exe", "test-netconnection", "netcat", "telnet", "curl ",
])
def test_models_have_no_execution_or_command_line_capability(text):
    assert text not in MODELS_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("path", [MODELS_FILE, PACKAGE_FILE, HERE])
def test_models_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
