import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.services.diagnostic_engine import SafePingBackend
from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeRequest,
    NetworkProbeTarget,
    NetworkProbeType,
)
from app.services.diagnostic_engine.network_probe_policy import NetworkProbePolicy
from app.services.diagnostic_engine.safe_ping_adapter import (
    PingBackendResult,
    SafePingAdapter,
)
from app.services.diagnostic_engine.safe_ping_backend import _PingTransportResult


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
BACKEND_FILE = ROOT / "app/services/diagnostic_engine/safe_ping_backend.py"
ADAPTER_FILE = BACKEND_FILE.with_name("safe_ping_adapter.py")
PACKAGE_FILE = BACKEND_FILE.with_name("__init__.py")
IPV4 = "192.0.2.10"
IPV6 = "2001:db8::10"


_DEFAULT_TRANSPORT_RESULT = object()


class FakeTransport:
    def __init__(self, returned=_DEFAULT_TRANSPORT_RESULT, error=None):
        self.returned = (
            _PingTransportResult(success=True, latency_ms=1.5, remote_ip=IPV4)
            if returned is _DEFAULT_TRANSPORT_RESULT
            else returned
        )
        self.error = error
        self.calls = []

    def probe(self, *, host, timeout_ms):
        self.calls.append((host, timeout_ms))
        if self.error is not None:
            raise self.error
        return self.returned


def backend(returned=_DEFAULT_TRANSPORT_RESULT, error=None, maximum=5000):
    transport = FakeTransport(returned, error)
    return SafePingBackend(transport, maximum), transport


def request(*, dry_run, host=IPV4, timeout=3000):
    return NetworkProbeRequest(
        probe_id="probe-1", session_id="session-1", request_id="request-1",
        action_id="action-1", grant_id="grant-1", probe_type=NetworkProbeType.PING,
        target=NetworkProbeTarget(host), timeout_ms=timeout, attempt=1,
        dry_run=dry_run, created_at_monotonic=1,
    )


def policy(**changes):
    values = dict(
        enabled=True, allow_ping=True, allow_real_probe=True,
        allow_private_addresses=True, allowed_hosts=(IPV4,),
    )
    values.update(changes)
    return NetworkProbePolicy(**values)


def test_default_construction_discovers_transport_without_calling_it():
    item = SafePingBackend()
    assert item.max_timeout_ms == 5000


def test_explicit_unavailable_transport_is_preserved():
    assert SafePingBackend(None).transport is None


def test_custom_transport_is_preserved():
    transport = FakeTransport()
    assert SafePingBackend(transport).transport is transport


def test_backend_is_frozen_and_has_no_global_mutable_state():
    with pytest.raises(FrozenInstanceError):
        SafePingBackend(None).max_timeout_ms = 1
    assert "calls" not in vars(SafePingBackend(None))


@pytest.mark.parametrize("maximum", [1, 100, 1000, 3000, 5000])
def test_conservative_hard_ceiling_values(maximum):
    assert SafePingBackend(None, maximum).max_timeout_ms == maximum


@pytest.mark.parametrize("maximum", [0, -1, 5001, True, False, 1.5, "5000", None])
def test_invalid_hard_ceiling_is_rejected(maximum):
    with pytest.raises(ValueError):
        SafePingBackend(None, maximum)


@pytest.mark.parametrize("host,normalized", [
    (IPV4, IPV4), ("192.0.2.1", "192.0.2.1"),
    ("203.0.113.254", "203.0.113.254"),
    (IPV6, IPV6), ("2001:0DB8:0:0:0:0:0:1", "2001:db8::1"),
])
def test_ip_literals_are_forwarded_normalized(host, normalized):
    returned = _PingTransportResult(success=True, latency_ms=2, remote_ip=normalized)
    subject, transport = backend(returned)
    result = subject.ping(host=host, timeout_ms=1000)
    assert result.success and result.remote_ip == normalized
    assert transport.calls == [(normalized, 1000)]


INVALID_HOSTS = (
    "", " ", " host", "host ", "localhost", "example.com", "test.invalid",
    "192.0.2.0/24", "2001:db8::/64", "192.0.2.1-254", "192.0.2.*",
    "host1,host2", "host1;host2", "host1 host2", "*", "*.example",
    "192.0.2.1,192.0.2.2", "[2001:db8::1]", "http://192.0.2.1", "192.0.2.1/path",
)


@pytest.mark.parametrize("host", INVALID_HOSTS)
@pytest.mark.parametrize("timeout", [1, 3000])
def test_non_literal_or_expanding_hosts_fail_before_transport(host, timeout):
    subject, transport = backend()
    result = subject.ping(host=host, timeout_ms=timeout)
    assert not result.success and not result.timed_out
    assert result.remote_ip is None and transport.calls == []


@pytest.mark.parametrize("host", [None, True, False, 1, (), [], {}, object()])
def test_non_string_host_is_rejected_without_transport(host):
    subject, transport = backend()
    assert not subject.ping(host=host, timeout_ms=1000).success
    assert transport.calls == []


@pytest.mark.parametrize("timeout", [0, -1, True, False, 1.5, "1000", None, object()])
def test_invalid_timeout_fails_before_transport(timeout):
    subject, transport = backend()
    result = subject.ping(host=IPV4, timeout_ms=timeout)
    assert not result.success and transport.calls == []


@pytest.mark.parametrize("timeout", [1, 10, 100, 999, 1000, 3000, 5000])
def test_valid_timeout_is_forwarded_exactly_when_under_ceiling(timeout):
    subject, transport = backend()
    subject.ping(host=IPV4, timeout_ms=timeout)
    assert transport.calls == [(IPV4, timeout)]


@pytest.mark.parametrize("requested,ceiling", [
    (5001, 5000), (10000, 5000), (3000, 1000), (1000, 500), (2, 1),
])
def test_hard_ceiling_never_increases_timeout(requested, ceiling):
    subject, transport = backend(maximum=ceiling)
    subject.ping(host=IPV4, timeout_ms=requested)
    assert transport.calls == [(IPV4, min(requested, ceiling))]


@pytest.mark.parametrize("latency", [None, 0, 0.0, 1, 1.5, 4999.9])
def test_success_preserves_observed_latency_and_exact_remote_ip(latency):
    observed = _PingTransportResult(success=True, latency_ms=latency, remote_ip=IPV4)
    subject, transport = backend(observed)
    result = subject.ping(host=IPV4, timeout_ms=1000)
    assert result == PingBackendResult(success=True, latency_ms=latency, remote_ip=IPV4)
    assert len(transport.calls) == 1


def test_timeout_is_controlled_and_has_no_measurement():
    subject, transport = backend(_PingTransportResult(timed_out=True))
    result = subject.ping(host=IPV4, timeout_ms=1000)
    assert result.timed_out and not result.success
    assert result.latency_ms is None and result.remote_ip is None
    assert len(transport.calls) == 1


@pytest.mark.parametrize("observed", [
    _PingTransportResult(),
    _PingTransportResult(success=True, latency_ms=1, remote_ip=None),
    _PingTransportResult(success=True, latency_ms=1, remote_ip="192.0.2.11"),
    _PingTransportResult(success=True, latency_ms=1, remote_ip="invalid"),
])
def test_failure_or_inconsistent_reply_never_invents_success(observed):
    subject, transport = backend(observed)
    result = subject.ping(host=IPV4, timeout_ms=1000)
    assert not result.success and result.remote_ip is None
    assert len(transport.calls) == 1


def test_unavailable_transport_returns_explicit_unavailable_state():
    result = SafePingBackend(None).ping(host=IPV4, timeout_ms=1000)
    assert result.unavailable and not result.success and not result.timed_out


def test_transport_unavailable_result_is_preserved():
    subject, transport = backend(_PingTransportResult(unavailable=True))
    result = subject.ping(host=IPV4, timeout_ms=1000)
    assert result.unavailable and len(transport.calls) == 1


@pytest.mark.parametrize("error", [
    RuntimeError("secret stack"), ValueError("C:/private/path"), OSError("environment data"),
])
def test_transport_exception_is_generic_and_called_once(error):
    subject, transport = backend(error=error)
    result = subject.ping(host=IPV4, timeout_ms=1000)
    assert result == PingBackendResult()
    assert len(transport.calls) == 1
    assert str(error) not in repr(result)


@pytest.mark.parametrize("malformed", [None, True, False, {}, (), [], "reply", 1, object()])
def test_malformed_transport_result_fails_closed(malformed):
    subject, transport = backend(malformed)
    result = subject.ping(host=IPV4, timeout_ms=1000)
    assert result == PingBackendResult() and len(transport.calls) == 1


def test_one_backend_call_is_one_transport_attempt_without_retry():
    subject, transport = backend(_PingTransportResult(timed_out=True))
    subject.ping(host=IPV4, timeout_ms=1000)
    assert transport.calls == [(IPV4, 1000)]


def test_inputs_and_transport_snapshot_are_not_modified():
    observed = _PingTransportResult(success=True, latency_ms=1, remote_ip=IPV4)
    subject, transport = backend(observed)
    before = deepcopy((IPV4, 1000, observed))
    subject.ping(host=IPV4, timeout_ms=1000)
    assert (IPV4, 1000, observed) == before
    assert transport.returned == observed


def test_adapter_dry_run_never_calls_safe_backend():
    subject, transport = backend()
    adapter = SafePingAdapter(policy(), subject)
    result = adapter.execute(request(dry_run=True), 10)
    assert result.success and transport.calls == []
    assert result.message == "Dry-run: ping validado; nenhum pacote foi enviado."


def test_adapter_default_policy_blocks_real_before_backend():
    subject, transport = backend()
    adapter = SafePingAdapter(NetworkProbePolicy(), subject)
    result = adapter.execute(request(dry_run=False), 10)
    assert not result.success and transport.calls == []


def test_explicit_policy_and_backend_delegate_once():
    subject, transport = backend()
    adapter = SafePingAdapter(policy(), subject)
    item = request(dry_run=False)
    before = deepcopy(item)
    result = adapter.execute(item, 10)
    assert result.success and transport.calls == [(IPV4, 3000)]
    assert item == before


def test_adapter_maps_backend_unavailable_to_generic_message():
    adapter = SafePingAdapter(policy(), SafePingBackend(None))
    result = adapter.execute(request(dry_run=False), 10)
    assert not result.success
    assert result.message == "Backend seguro de ping indisponível."


@pytest.mark.parametrize("host,flag", [
    ("127.0.0.1", "allow_loopback"),
    ("169.254.1.1", "allow_link_local"),
    ("224.0.0.1", "allow_multicast"),
    ("240.0.0.1", "allow_reserved"),
    ("0.0.0.0", "allow_unspecified"),
    ("10.0.0.1", "allow_private_addresses"),
])
def test_adapter_policy_remains_authoritative_for_special_addresses(host, flag):
    subject, transport = backend(_PingTransportResult(success=True, remote_ip=host))
    configured = policy(allowed_hosts=(host,), **{flag: False})
    result = SafePingAdapter(configured, subject).execute(request(dry_run=False, host=host), 10)
    assert not result.success and transport.calls == []


@pytest.mark.parametrize("name", [
    "ping_many", "scan_hosts", "scan_network", "discover_hosts", "check_port",
    "connect", "http_probe", "tcp_probe",
])
def test_no_scan_batch_or_port_api_exists(name):
    assert not hasattr(SafePingBackend, name)


@pytest.mark.parametrize("forbidden", [
    "subprocess", "socket", "requests", "httpx", "urllib", "asyncio",
    "multiprocessing", "threading",
])
def test_forbidden_modules_are_not_imported(forbidden):
    tree = ast.parse(BACKEND_FILE.read_text(encoding="utf-8"))
    imports = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert all(name != forbidden and not name.startswith(forbidden + ".") for name in imports)


@pytest.mark.parametrize("forbidden", [
    "shell=true", "os.system", "os.popen", "powershell", "cmd.exe", "ping.exe",
    "test-netconnection", "nmap", "masscan", "getaddrinfo", "gethostbyname",
    "socket(", "checksum", "sleep(", "retry(", "backoff(", "connect(",
])
def test_forbidden_execution_scan_dns_and_retry_patterns_are_absent(forbidden):
    assert forbidden not in BACKEND_FILE.read_text(encoding="utf-8").casefold()


@pytest.mark.parametrize("private", [
    "username", "hostname", "environment", "command_line", "mac", "interfaces",
    "routes", "dns", "gateway", "credentials", "password", "token",
])
def test_backend_result_has_no_private_or_environment_fields(private):
    assert not hasattr(PingBackendResult(), private)


def test_safe_ping_backend_is_public_but_internal_transport_is_not():
    import app.services.diagnostic_engine as package

    assert package.SafePingBackend is SafePingBackend
    assert "SafePingBackend" in package.__all__
    assert "_WindowsIcmpTransport" not in package.__all__


@pytest.mark.parametrize("path", [BACKEND_FILE, ADAPTER_FILE, HERE, PACKAGE_FILE])
def test_sprint_files_are_utf8_without_bom(path):
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    data.decode("utf-8")
