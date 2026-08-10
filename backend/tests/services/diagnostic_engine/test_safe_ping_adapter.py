import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.services.diagnostic_engine import SafePingAdapter
from app.services.diagnostic_engine.safe_ping_adapter import (
    PingBackendProtocol,
    PingBackendResult,
)
from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeRequest,
    NetworkProbeState,
    NetworkProbeTarget,
    NetworkProbeType,
)
from app.services.diagnostic_engine.network_probe_policy import NetworkProbePolicy


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ADAPTER_FILE = ROOT / "app/services/diagnostic_engine/safe_ping_adapter.py"
PACKAGE_FILE = ADAPTER_FILE.with_name("__init__.py")
TEST_HOST = "192.0.2.10"


_DEFAULT_RESULT = object()


class FakeBackend:
    def __init__(self, result=_DEFAULT_RESULT, error=None):
        self.result = PingBackendResult(success=True, latency_ms=1.25) if result is _DEFAULT_RESULT else result
        self.error = error
        self.calls = []

    def ping(self, *, host, timeout_ms):
        self.calls.append((host, timeout_ms))
        if self.error is not None:
            raise self.error
        return self.result


def policy(host=TEST_HOST, *, real=False, **changes):
    values = dict(
        enabled=True,
        allow_ping=True,
        allow_real_probe=real,
        allow_private_addresses=True,
        allowed_hosts=(host,),
    )
    values.update(changes)
    return NetworkProbePolicy(**values)


def request(*, host=TEST_HOST, dry_run=True, timeout=3000, attempt=1,
            probe_type=NetworkProbeType.PING, port=None, **changes):
    values = dict(
        probe_id="probe-1",
        session_id="session-1",
        request_id="request-1",
        action_id="action-1",
        grant_id="grant-1",
        probe_type=probe_type,
        target=NetworkProbeTarget(host, port),
        timeout_ms=timeout,
        attempt=attempt,
        dry_run=dry_run,
        created_at_monotonic=1,
    )
    values.update(changes)
    return NetworkProbeRequest(**values)


def execute(*, configured=None, backend=None, item=None, now=10):
    configured = policy() if configured is None else configured
    item = request() if item is None else item
    return SafePingAdapter(configured, backend).execute(item, now)


def test_default_constructor_is_fail_closed():
    adapter = SafePingAdapter()
    assert adapter.policy == NetworkProbePolicy() and adapter.backend is None


def test_none_policy_uses_default():
    assert SafePingAdapter(None).policy == NetworkProbePolicy()


def test_custom_policy_and_backend_are_preserved():
    configured, backend = policy(), FakeBackend()
    adapter = SafePingAdapter(configured, backend)
    assert adapter.policy is configured and adapter.backend is backend


def test_adapter_is_frozen():
    with pytest.raises(FrozenInstanceError):
        SafePingAdapter().policy = policy()


@pytest.mark.parametrize("success,timed_out,latency", [
    (True, False, None), (True, False, 0), (True, False, 1.5),
    (False, False, None), (False, True, None),
])
def test_backend_result_valid_combinations(success, timed_out, latency):
    result = PingBackendResult(success, timed_out, latency)
    assert (result.success, result.timed_out, result.latency_ms) == (success, timed_out, latency)


@pytest.mark.parametrize("success,timed_out,latency", [
    (True, True, None), (False, False, 1), (False, True, 1),
    (True, False, -1), (True, False, True), (True, False, "1"),
])
def test_backend_result_rejects_malformed_data(success, timed_out, latency):
    with pytest.raises(ValueError):
        PingBackendResult(success, timed_out, latency)


def test_backend_protocol_is_runtime_checkable():
    assert isinstance(FakeBackend(), PingBackendProtocol)


@pytest.mark.parametrize("probe_type,port", [
    (NetworkProbeType.TCP_PORT_CHECK, 443),
])
def test_tcp_port_check_is_blocked(probe_type, port):
    result = execute(item=request(probe_type=probe_type, port=port))
    assert result.state == NetworkProbeState.BLOCKED and not result.success


@pytest.mark.parametrize("value", [None, object(), "request", {}, (), []])
def test_non_request_values_fail_closed(value):
    result = SafePingAdapter(policy()).execute(value, 10)
    assert result.state == NetworkProbeState.BLOCKED


@pytest.mark.parametrize("now", [-1, True, False, "10", None, object()])
def test_invalid_monotonic_time_is_blocked(now):
    assert execute(now=now).state == NetworkProbeState.BLOCKED


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"allow_ping": False},
    {"enabled": False, "allow_ping": False},
])
def test_policy_switches_block_dry_run(changes):
    assert execute(configured=policy(**changes)).state == NetworkProbeState.BLOCKED


@pytest.mark.parametrize("real,backend", [(False, None), (False, FakeBackend())])
def test_real_probe_policy_disabled_never_calls_backend(real, backend):
    item = request(dry_run=False)
    result = execute(configured=policy(real=real), backend=backend, item=item)
    assert result.state == NetworkProbeState.BLOCKED
    if backend is not None:
        assert backend.calls == []


def test_dry_run_returns_structural_success_and_exact_message():
    result = execute()
    assert result.state == NetworkProbeState.SUCCESS and result.success
    assert result.message == "Dry-run: ping validado; nenhum pacote foi enviado."


@pytest.mark.parametrize("backend", [None, FakeBackend(), FakeBackend(error=RuntimeError("raw secret"))])
def test_dry_run_never_calls_backend(backend):
    result = execute(backend=backend)
    assert result.success
    if backend is not None:
        assert backend.calls == []


def test_dry_run_never_claims_measurement_or_remote_endpoint():
    result = execute()
    assert result.latency_ms is None and result.remote_ip is None and result.remote_port is None


INVALID_HOSTS = (
    "192.168.1.0/24", "192.168.1.1-254", "192.168.1.*", "host1,host2",
    "host1;host2", "host1 host2", "*", "*.local", "host?", "host/path",
)


@pytest.mark.parametrize("host", INVALID_HOSTS)
def test_scan_or_multiple_host_syntax_cannot_form_request(host):
    with pytest.raises(ValueError):
        request(host=host)


@pytest.mark.parametrize("allowed,actual", [
    (TEST_HOST, "192.0.2.11"), ("192.0.2.11", TEST_HOST),
    ("198.51.100.10", TEST_HOST), (TEST_HOST, "198.51.100.10"),
])
def test_only_exact_allowlisted_host_is_accepted(allowed, actual):
    assert execute(configured=policy(host=allowed), item=request(host=actual)).state == NetworkProbeState.BLOCKED


@pytest.mark.parametrize("host,flag", [
    ("127.0.0.1", "allow_loopback"),
    ("169.254.1.1", "allow_link_local"),
    ("224.0.0.1", "allow_multicast"),
    ("240.0.0.1", "allow_reserved"),
    ("0.0.0.0", "allow_unspecified"),
    ("10.0.0.1", "allow_private_addresses"),
])
def test_special_addresses_are_blocked_without_exact_permission(host, flag):
    configured = policy(host=host, **{flag: False})
    assert execute(configured=configured, item=request(host=host)).state == NetworkProbeState.BLOCKED


@pytest.mark.parametrize("host,flag", [
    ("127.0.0.1", "allow_loopback"),
    ("169.254.1.1", "allow_link_local"),
    ("224.0.0.1", "allow_multicast"),
    ("240.0.0.1", "allow_reserved"),
    ("0.0.0.0", "allow_unspecified"),
    ("10.0.0.1", "allow_private_addresses"),
])
def test_special_addresses_can_only_be_explicitly_permitted_for_dry_run(host, flag):
    configured = policy(host=host, **{flag: True})
    assert execute(configured=configured, item=request(host=host)).success


def test_limited_broadcast_is_blocked_by_default():
    host = "255.255.255.255"
    configured = policy(host=host, allow_reserved=True, allow_broadcast=False)
    assert execute(configured=configured, item=request(host=host)).state == NetworkProbeState.BLOCKED


@pytest.mark.parametrize("allow_hostnames,allow_dns", [
    (False, False), (True, False), (False, True),
])
def test_hostname_is_blocked_without_existing_policy_permissions(allow_hostnames, allow_dns):
    host = "test.invalid"
    configured = policy(host=host, allow_hostnames=allow_hostnames, allow_dns_resolution=allow_dns)
    assert execute(configured=configured, item=request(host=host)).state == NetworkProbeState.BLOCKED


def test_hostname_dry_run_is_structural_only_when_policy_accepts_it():
    host = "test.invalid"
    configured = policy(host=host, allow_hostnames=True, allow_dns_resolution=True)
    result = execute(configured=configured, item=request(host=host))
    assert result.success and result.remote_ip is None


def test_hostname_real_execution_is_always_blocked_without_resolution():
    host = "test.invalid"
    configured = policy(host=host, real=True, allow_hostnames=True, allow_dns_resolution=True)
    backend = FakeBackend()
    result = execute(configured=configured, backend=backend, item=request(host=host, dry_run=False))
    assert result.state == NetworkProbeState.BLOCKED and backend.calls == []


@pytest.mark.parametrize("attempt", [2, 3, 100])
def test_more_than_one_attempt_is_blocked_without_retry(attempt):
    assert execute(item=request(attempt=attempt)).state == NetworkProbeState.BLOCKED


@pytest.mark.parametrize("timeout", [1, 100, 2999, 3000, 5000])
def test_valid_timeout_is_accepted_in_dry_run(timeout):
    assert execute(item=request(timeout=timeout)).success


@pytest.mark.parametrize("timeout", [5001, 6000, 10000])
def test_timeout_above_policy_limit_is_blocked(timeout):
    assert execute(item=request(timeout=timeout)).state == NetworkProbeState.BLOCKED


def test_absent_backend_fails_closed_for_real_ping():
    result = execute(configured=policy(real=True), item=request(dry_run=False))
    assert result.state == NetworkProbeState.FAILED
    assert result.message == "Backend seguro de ping indisponível."


def test_fake_backend_success_is_called_once_with_exact_values():
    backend = FakeBackend(PingBackendResult(success=True, latency_ms=2.5))
    result = execute(configured=policy(real=True), backend=backend, item=request(dry_run=False, timeout=1234))
    assert result.state == NetworkProbeState.SUCCESS and result.success
    assert backend.calls == [(TEST_HOST, 1234)]
    assert result.remote_port is None and result.remote_ip is None and result.latency_ms is None


def test_fake_backend_timeout_is_generic_and_not_retried():
    backend = FakeBackend(PingBackendResult(timed_out=True))
    result = execute(configured=policy(real=True), backend=backend, item=request(dry_run=False))
    assert result.state == NetworkProbeState.TIMED_OUT and not result.success
    assert result.message == "Tempo limite excedido ao executar ping."
    assert len(backend.calls) == 1


def test_fake_backend_no_response_is_generic():
    backend = FakeBackend(PingBackendResult())
    result = execute(configured=policy(real=True), backend=backend, item=request(dry_run=False))
    assert result.state == NetworkProbeState.FAILED and not result.success
    assert result.message == "Host não respondeu ao ping."


@pytest.mark.parametrize("error", [RuntimeError("raw stdout secret"), ValueError("C:/private/path"), OSError("environment")])
def test_backend_exceptions_do_not_leak_details(error):
    backend = FakeBackend(error=error)
    result = execute(configured=policy(real=True), backend=backend, item=request(dry_run=False))
    assert result.message == "Falha ao executar ping."
    assert str(error) not in result.message and len(backend.calls) == 1


@pytest.mark.parametrize("malformed", [None, True, False, {}, (), object(), "success"])
def test_malformed_backend_result_fails_generically(malformed):
    backend = FakeBackend(malformed)
    result = execute(configured=policy(real=True), backend=backend, item=request(dry_run=False))
    assert result.state == NetworkProbeState.FAILED and result.message == "Falha ao executar ping."


def test_request_target_policy_and_backend_result_are_not_mutated():
    item = request(dry_run=False)
    configured = policy(real=True)
    backend_result = PingBackendResult(success=True, latency_ms=1)
    backend = FakeBackend(backend_result)
    originals = deepcopy((item, item.target, configured, backend_result))
    execute(configured=configured, backend=backend, item=item)
    assert (item, item.target, configured, backend_result) == originals


@pytest.mark.parametrize("now", [0, 0.0, 1, 10.5, 999999])
def test_valid_monotonic_time_is_preserved_in_result(now):
    result = execute(now=now)
    assert result.started_at_monotonic == float(now)
    assert result.finished_at_monotonic == float(now)


@pytest.mark.parametrize("field,expected", [
    ("probe_id", "probe-1"),
    ("session_id", "session-1"),
    ("request_id", "request-1"),
    ("action_id", "action-1"),
    ("grant_id", "grant-1"),
])
def test_request_identifiers_are_preserved(field, expected):
    item = request()
    before = getattr(item, field)
    result = execute(item=item)
    assert before == expected and getattr(item, field) == expected and result.probe_id == item.probe_id


@pytest.mark.parametrize("timeout", [1, 250, 3000, 5000])
def test_real_backend_receives_exact_timeout_without_reinterpretation(timeout):
    backend = FakeBackend()
    execute(configured=policy(real=True), backend=backend, item=request(dry_run=False, timeout=timeout))
    assert backend.calls == [(TEST_HOST, timeout)]


@pytest.mark.parametrize("name", ["ping_many", "scan_hosts", "scan_network", "discover_hosts", "check_port"])
def test_batch_scan_and_tcp_apis_do_not_exist(name):
    assert not hasattr(SafePingAdapter, name)


@pytest.mark.parametrize("forbidden", [
    "socket", "subprocess", "requests", "httpx", "urllib.request", "psutil",
])
def test_forbidden_modules_are_not_imported(forbidden):
    tree = ast.parse(ADAPTER_FILE.read_text(encoding="utf-8"))
    imports = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert all(name != forbidden and not name.startswith(forbidden + ".") for name in imports)


@pytest.mark.parametrize("forbidden", [
    "shell=true", "os.system", "os.popen", "powershell", "cmd.exe", "ping.exe",
    "test-netconnection", "netcat", "getaddrinfo", "gethostbyname", "connect_ex",
])
def test_forbidden_execution_primitives_are_absent(forbidden):
    assert forbidden not in ADAPTER_FILE.read_text(encoding="utf-8").casefold()


def test_public_export():
    namespace = {}
    exec("from app.services.diagnostic_engine import SafePingAdapter", namespace)
    assert namespace["SafePingAdapter"] is SafePingAdapter


@pytest.mark.parametrize("name", ["PingBackendResult", "PingBackendProtocol"])
def test_backend_contracts_do_not_expand_package_public_api(name):
    import app.services.diagnostic_engine as package

    assert name not in package.__all__


@pytest.mark.parametrize("path", [ADAPTER_FILE, HERE, PACKAGE_FILE])
def test_files_are_utf8_without_bom(path):
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    data.decode("utf-8")


@pytest.mark.parametrize("enabled,allow_ping,allow_real,dry_run,backend_available", [
    (enabled, allow_ping, allow_real, dry_run, backend_available)
    for enabled in (False, True)
    for allow_ping in (False, True)
    for allow_real in (False, True)
    for dry_run in (False, True)
    for backend_available in (False, True)
])
def test_policy_combinations_never_bypass_required_gates(enabled, allow_ping, allow_real, dry_run, backend_available):
    configured = policy(enabled=enabled, allow_ping=allow_ping, allow_real_probe=allow_real)
    backend = FakeBackend() if backend_available else None
    result = execute(configured=configured, backend=backend, item=request(dry_run=dry_run))
    expected = enabled and allow_ping and (dry_run or (allow_real and backend_available))
    assert result.success is expected
    if backend is not None:
        assert len(backend.calls) == (1 if expected and not dry_run else 0)
