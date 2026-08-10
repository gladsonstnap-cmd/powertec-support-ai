import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import MappingProxyType

import pytest

from app.services.diagnostic_engine import (
    NetworkProbeDispatcher,
    NetworkProbeDispatchResult,
)
from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeBlockReason,
    NetworkProbeRequest,
    NetworkProbeResult,
    NetworkProbeState,
    NetworkProbeTarget,
    NetworkProbeType,
)
from app.services.diagnostic_engine.network_probe_policy import NetworkProbePolicy
from app.services.diagnostic_engine.safe_ping_adapter import SafePingAdapter


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
DISPATCHER_FILE = ROOT / "app/services/diagnostic_engine/network_probe_dispatcher.py"
PACKAGE_FILE = DISPATCHER_FILE.with_name("__init__.py")
TEST_HOST = "192.0.2.10"


def policy(**changes):
    values = dict(
        enabled=True,
        allow_ping=True,
        allow_private_addresses=True,
        allowed_hosts=(TEST_HOST,),
    )
    values.update(changes)
    return NetworkProbePolicy(**values)


def request(*, dry_run=True, timeout=3000, attempt=1,
            probe_type=NetworkProbeType.PING, host=TEST_HOST, port=None):
    return NetworkProbeRequest(
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


def probe_result(*, success=True, probe_id="probe-1", message="snapshot",
                 started=10, finished=10):
    state = NetworkProbeState.SUCCESS if success else NetworkProbeState.BLOCKED
    return NetworkProbeResult(
        probe_id=probe_id,
        state=state,
        success=success,
        block_reason=None if success else NetworkProbeBlockReason.VALIDATION_FAILED,
        message=message,
        started_at_monotonic=started,
        finished_at_monotonic=finished,
        metadata={"safe": "snapshot"},
    )


_DEFAULT_PROBE_RESULT = object()


class PingSpy(SafePingAdapter):
    def __init__(self, configured, returned=_DEFAULT_PROBE_RESULT, error=None):
        super().__init__(policy=configured)
        object.__setattr__(self, "calls", [])
        object.__setattr__(
            self,
            "returned",
            probe_result() if returned is _DEFAULT_PROBE_RESULT else returned,
        )
        object.__setattr__(self, "error", error)

    def execute(self, item, now):
        self.calls.append((item, now))
        if self.error is not None:
            raise self.error
        return self.returned


def test_default_constructor_uses_default_policy_and_adapter():
    dispatcher = NetworkProbeDispatcher()
    assert dispatcher.policy == NetworkProbePolicy()
    assert isinstance(dispatcher.ping_adapter, SafePingAdapter)


def test_default_adapter_uses_identical_policy_instance():
    configured = policy()
    dispatcher = NetworkProbeDispatcher(configured)
    assert dispatcher.ping_adapter.policy is configured


def test_custom_adapter_is_preserved():
    configured = policy()
    adapter = PingSpy(configured)
    assert NetworkProbeDispatcher(configured, adapter).ping_adapter is adapter


@pytest.mark.parametrize("field,value", [
    ("policy", object()), ("policy", "policy"),
    ("ping_adapter", object()), ("ping_adapter", "adapter"),
])
def test_constructor_rejects_malformed_dependencies(field, value):
    with pytest.raises(ValueError):
        NetworkProbeDispatcher(**{field: value})


def test_divergent_injected_policy_fails_closed_at_construction():
    with pytest.raises(ValueError, match="same policy"):
        NetworkProbeDispatcher(policy(), PingSpy(policy(allow_ping=False)))


def test_dispatcher_and_result_are_frozen():
    with pytest.raises(FrozenInstanceError):
        NetworkProbeDispatcher().policy = policy()
    with pytest.raises(FrozenInstanceError):
        NetworkProbeDispatchResult().success = True


def test_registry_is_private_mapping_proxy_and_immutable():
    dispatcher = NetworkProbeDispatcher()
    assert isinstance(dispatcher._registry, MappingProxyType)
    with pytest.raises(TypeError):
        dispatcher._registry[NetworkProbeType.TCP_PORT_CHECK] = object()


def test_registry_contains_only_ping():
    dispatcher = NetworkProbeDispatcher()
    assert tuple(dispatcher._registry) == (NetworkProbeType.PING,)


def test_supported_probe_types_is_deterministic_tuple():
    dispatcher = NetworkProbeDispatcher()
    assert dispatcher.supported_probe_types() == (NetworkProbeType.PING,)
    assert isinstance(dispatcher.supported_probe_types(), tuple)
    assert dispatcher.supported_probe_types() == dispatcher.supported_probe_types()


@pytest.mark.parametrize("value,expected", [
    (NetworkProbeType.PING, True),
    (NetworkProbeType.TCP_PORT_CHECK, False),
    ("PING", False), ("ping", False), (None, False), (1, False),
    (True, False), (object(), False), ("", False), ((), False),
])
def test_contains_is_exact_without_coercion(value, expected):
    assert NetworkProbeDispatcher().contains(value) is expected


def test_resolve_ping_returns_exact_adapter_instance():
    configured = policy()
    adapter = PingSpy(configured)
    dispatcher = NetworkProbeDispatcher(configured, adapter)
    assert dispatcher.resolve(NetworkProbeType.PING) is adapter


@pytest.mark.parametrize("value", [
    NetworkProbeType.TCP_PORT_CHECK, "PING", "ping", "TCP_PORT_CHECK",
    None, 1, True, object(), "", (), [], {},
])
def test_resolve_unknown_has_no_fallback(value):
    assert NetworkProbeDispatcher().resolve(value) is None


def test_valid_ping_is_delegated_exactly_once():
    configured = policy()
    adapter = PingSpy(configured)
    item = request()
    result = NetworkProbeDispatcher(configured, adapter).dispatch(item, 10)
    assert result.success and adapter.calls == [(item, 10)]


@pytest.mark.parametrize("now", [0, 0.0, 1, 10.5, 99999])
def test_valid_time_is_forwarded_unchanged(now):
    configured = policy()
    adapter = PingSpy(configured)
    item = request()
    NetworkProbeDispatcher(configured, adapter).dispatch(item, now)
    assert adapter.calls == [(item, now)]


@pytest.mark.parametrize("now", [-1, True, False, "10", None, object()])
def test_invalid_time_is_blocked_before_adapter(now):
    configured = policy()
    adapter = PingSpy(configured)
    result = NetworkProbeDispatcher(configured, adapter).dispatch(request(), now)
    assert not result.success and adapter.calls == []


@pytest.mark.parametrize("item", [None, object(), "request", 1, True, (), [], {}])
def test_malformed_request_is_blocked(item):
    configured = policy()
    adapter = PingSpy(configured)
    result = NetworkProbeDispatcher(configured, adapter).dispatch(item, 10)
    assert not result.success and result.result is None and adapter.calls == []


def test_tcp_port_check_is_unsupported_and_never_delegated():
    configured = policy()
    adapter = PingSpy(configured)
    item = request(probe_type=NetworkProbeType.TCP_PORT_CHECK, port=443)
    result = NetworkProbeDispatcher(configured, adapter).dispatch(item, 10)
    assert not result.success and result.errors == ("Tipo de probe não suportado.",)
    assert adapter.calls == []


@pytest.mark.parametrize("field,value", [
    ("probe_id", ""), ("session_id", ""), ("request_id", ""),
    ("action_id", ""), ("grant_id", ""),
    ("probe_id", " "), ("session_id", None), ("grant_id", 1),
])
def test_corrupted_identifiers_fail_closed(field, value):
    configured = policy()
    adapter = PingSpy(configured)
    item = request()
    object.__setattr__(item, field, value)
    result = NetworkProbeDispatcher(configured, adapter).dispatch(item, 10)
    assert not result.success and adapter.calls == []


@pytest.mark.parametrize("timeout", [0, -1, 5001, True, False, 1.5, "3000", None])
def test_corrupted_or_excessive_timeout_is_blocked(timeout):
    configured = policy()
    adapter = PingSpy(configured)
    item = request()
    object.__setattr__(item, "timeout_ms", timeout)
    result = NetworkProbeDispatcher(configured, adapter).dispatch(item, 10)
    assert not result.success and adapter.calls == []


@pytest.mark.parametrize("timeout", [1, 100, 2999, 3000, 5000])
def test_valid_timeout_is_not_rewritten(timeout):
    configured = policy()
    adapter = PingSpy(configured)
    item = request(timeout=timeout)
    NetworkProbeDispatcher(configured, adapter).dispatch(item, 10)
    assert adapter.calls[0][0].timeout_ms == timeout


@pytest.mark.parametrize("attempt", [0, -1, 2, 3, True, False, 1.5, "1"])
def test_invalid_attempt_is_blocked_without_retry(attempt):
    configured = policy()
    adapter = PingSpy(configured)
    item = request()
    object.__setattr__(item, "attempt", attempt)
    result = NetworkProbeDispatcher(configured, adapter).dispatch(item, 10)
    assert not result.success and adapter.calls == []


@pytest.mark.parametrize("dry_run", [True, False])
def test_dry_run_flag_is_forwarded_unchanged(dry_run):
    configured = policy(allow_real_probe=True)
    adapter = PingSpy(configured)
    item = request(dry_run=dry_run)
    NetworkProbeDispatcher(configured, adapter).dispatch(item, 10)
    assert adapter.calls[0][0].dry_run is dry_run


@pytest.mark.parametrize("value", [None, 0, 1, "true", (), object()])
def test_corrupted_dry_run_is_blocked(value):
    configured = policy()
    adapter = PingSpy(configured)
    item = request()
    object.__setattr__(item, "dry_run", value)
    result = NetworkProbeDispatcher(configured, adapter).dispatch(item, 10)
    assert not result.success and adapter.calls == []


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"allow_ping": False},
    {"enabled": False, "allow_ping": False},
])
def test_policy_blocks_before_delegation(changes):
    configured = policy(**changes)
    adapter = PingSpy(configured)
    result = NetworkProbeDispatcher(configured, adapter).dispatch(request(), 10)
    assert not result.success and adapter.calls == []


def test_default_policy_blocks_without_calling_default_adapter():
    result = NetworkProbeDispatcher().dispatch(request(), 10)
    assert not result.success and result.result is None


@pytest.mark.parametrize("host", ["192.0.2.11", "198.51.100.10", "203.0.113.10"])
def test_host_outside_allowlist_is_blocked_before_adapter(host):
    configured = policy()
    adapter = PingSpy(configured)
    result = NetworkProbeDispatcher(configured, adapter).dispatch(request(host=host), 10)
    assert not result.success and adapter.calls == []


INVALID_HOSTS = (
    "192.168.1.0/24", "192.168.1.1-254", "192.168.1.*", "host1,host2",
    "host1;host2", "host1 host2", "*", "*.local", "host?", "host/path",
)


@pytest.mark.parametrize("host", INVALID_HOSTS)
def test_scan_syntax_cannot_be_constructed_or_expanded(host):
    with pytest.raises(ValueError):
        request(host=host)


def test_request_host_target_timeout_attempt_and_grant_are_preserved():
    configured = policy()
    adapter = PingSpy(configured)
    item = request(timeout=1234, attempt=1)
    original = deepcopy(item)
    NetworkProbeDispatcher(configured, adapter).dispatch(item, 10)
    forwarded = adapter.calls[0][0]
    assert forwarded == item == original
    assert forwarded.target is item.target
    assert forwarded.grant_id == "grant-1"


def test_adapter_result_snapshot_is_preserved_by_value():
    configured = policy()
    snapshot = probe_result(message="exact message", started=4, finished=5)
    adapter = PingSpy(configured, snapshot)
    dispatched = NetworkProbeDispatcher(configured, adapter).dispatch(request(), 10)
    assert dispatched.result == snapshot
    assert dispatched.result.state == snapshot.state
    assert dispatched.result.message == "exact message"
    assert dispatched.result.started_at_monotonic == 4
    assert dispatched.result.finished_at_monotonic == 5
    assert dispatched.result.latency_ms == snapshot.latency_ms
    assert dispatched.result.remote_ip == snapshot.remote_ip
    assert dispatched.result.remote_port == snapshot.remote_port


def test_failed_valid_result_is_preserved_without_inventing_success():
    configured = policy()
    snapshot = probe_result(success=False)
    dispatched = NetworkProbeDispatcher(configured, PingSpy(configured, snapshot)).dispatch(request(), 10)
    assert not dispatched.success and dispatched.result == snapshot


@pytest.mark.parametrize("bad", [None, object(), True, False, {}, (), "result", 1])
def test_invalid_adapter_result_fails_closed(bad):
    configured = policy()
    adapter = PingSpy(configured, bad)
    dispatched = NetworkProbeDispatcher(configured, adapter).dispatch(request(), 10)
    assert not dispatched.success and dispatched.result is None
    assert dispatched.errors == ("Falha no probe de rede.",) and len(adapter.calls) == 1


def test_result_with_wrong_probe_id_is_rejected():
    configured = policy()
    adapter = PingSpy(configured, probe_result(probe_id="other"))
    dispatched = NetworkProbeDispatcher(configured, adapter).dispatch(request(), 10)
    assert not dispatched.success and dispatched.result is None


@pytest.mark.parametrize("error", [
    RuntimeError("secret stack"), ValueError("C:/private/path"), OSError("local environment"),
])
def test_adapter_exception_is_generic_and_called_once(error):
    configured = policy()
    adapter = PingSpy(configured, error=error)
    dispatched = NetworkProbeDispatcher(configured, adapter).dispatch(request(), 10)
    assert dispatched.errors == ("Falha no probe de rede.",)
    assert str(error) not in " ".join(dispatched.errors) and len(adapter.calls) == 1


def test_dispatch_result_defensively_copies_adapter_snapshot():
    configured = policy()
    snapshot = probe_result()
    dispatched = NetworkProbeDispatcher(configured, PingSpy(configured, snapshot)).dispatch(request(), 10)
    snapshot.metadata["changed"] = True
    assert dispatched.result.metadata == {"safe": "snapshot"}


@pytest.mark.parametrize("name", [
    "dispatch_many", "ping_many", "scan_hosts", "scan_network", "discover_hosts", "check_port",
])
def test_no_batch_scan_or_tcp_api_exists(name):
    assert not hasattr(NetworkProbeDispatcher, name)


@pytest.mark.parametrize("forbidden", [
    "socket", "subprocess", "requests", "httpx", "urllib.request", "psutil", "os",
])
def test_forbidden_modules_are_not_imported(forbidden):
    tree = ast.parse(DISPATCHER_FILE.read_text(encoding="utf-8"))
    imports = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert all(name != forbidden and not name.startswith(forbidden + ".") for name in imports)


@pytest.mark.parametrize("forbidden", [
    "powershell", "cmd.exe", "ping.exe", "test-netconnection", "netcat", "nmap",
    "getaddrinfo", "gethostbyname", "consume_grant", "session_engine", "session_models",
    "localadapterdispatcher", "localnetworkdiagnosticadapter",
])
def test_forbidden_execution_and_cross_layer_references_are_absent(forbidden):
    assert forbidden not in DISPATCHER_FILE.read_text(encoding="utf-8").casefold()


@pytest.mark.parametrize("name", ["NetworkProbeDispatcher", "NetworkProbeDispatchResult"])
def test_public_exports(name):
    namespace = {}
    exec(f"from app.services.diagnostic_engine import {name}", namespace)
    assert namespace[name].__name__ == name


@pytest.mark.parametrize("path", [DISPATCHER_FILE, HERE, PACKAGE_FILE])
def test_files_are_utf8_without_bom(path):
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    data.decode("utf-8")


@pytest.mark.parametrize("enabled,allow_ping,allow_real,dry_run", [
    (enabled, allow_ping, allow_real, dry_run)
    for enabled in (False, True)
    for allow_ping in (False, True)
    for allow_real in (False, True)
    for dry_run in (False, True)
])
def test_policy_matrix_never_bypasses_dispatch_guards(enabled, allow_ping, allow_real, dry_run):
    configured = policy(enabled=enabled, allow_ping=allow_ping, allow_real_probe=allow_real)
    adapter = PingSpy(configured)
    dispatched = NetworkProbeDispatcher(configured, adapter).dispatch(request(dry_run=dry_run), 10)
    expected_call = enabled and allow_ping and (dry_run or allow_real)
    assert len(adapter.calls) == (1 if expected_call else 0)
    assert dispatched.success is expected_call
