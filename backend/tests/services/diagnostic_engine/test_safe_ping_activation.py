import ast
import sys
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import app.services.diagnostic_engine.safe_ping_activation as activation_module
from app.services.diagnostic_engine import SafePingActivationPolicy, SafePingBackendFactory
from app.services.diagnostic_engine.network_probe_dispatcher import NetworkProbeDispatcher
from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeRequest, NetworkProbeTarget, NetworkProbeType,
)
from app.services.diagnostic_engine.network_probe_policy import NetworkProbePolicy
from app.services.diagnostic_engine.safe_ping_adapter import PingBackendResult, SafePingAdapter
from app.services.diagnostic_engine.safe_ping_backend import SafePingBackend


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ACTIVATION_FILE = ROOT / "app/services/diagnostic_engine/safe_ping_activation.py"
DISPATCHER_FILE = ACTIVATION_FILE.with_name("network_probe_dispatcher.py")
PACKAGE_FILE = ACTIVATION_FILE.with_name("__init__.py")
HOST = "192.0.2.10"


def network_policy(**changes):
    values = dict(
        enabled=True, allow_ping=True, allow_real_probe=True,
        allow_private_addresses=True, allowed_hosts=(HOST,),
    )
    values.update(changes)
    return NetworkProbePolicy(**values)


def activation_policy(**changes):
    values = dict(enabled=True, allow_native_windows_backend=True)
    values.update(changes)
    return SafePingActivationPolicy(**values)


def build(factory=None, *, policy=None, explicit=True, probe_type=NetworkProbeType.PING,
          timeout=1000, attempts=1):
    return (factory or SafePingBackendFactory()).build(
        network_probe_policy=policy or network_policy(),
        explicit_real_execution=explicit,
        probe_type=probe_type,
        timeout_ms=timeout,
        attempts=attempts,
    )


def request(*, dry_run=False, timeout=1000, attempt=1,
            probe_type=NetworkProbeType.PING, port=None):
    return NetworkProbeRequest(
        probe_id="probe-1", session_id="session-1", request_id="request-1",
        action_id="action-1", grant_id="grant-1", probe_type=probe_type,
        target=NetworkProbeTarget(HOST, port), timeout_ms=timeout, attempt=attempt,
        dry_run=dry_run, created_at_monotonic=1,
    )


class FakeBackend:
    def __init__(self, *, max_timeout_ms=5000):
        self.max_timeout_ms = max_timeout_ms
        self.calls = []

    def ping(self, *, host, timeout_ms):
        self.calls.append((host, timeout_ms))
        return PingBackendResult(success=True, latency_ms=1, remote_ip=host)


class ConstructorSpy:
    def __init__(self, returned=None, error=None):
        self.returned = returned or FakeBackend()
        self.error = error
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        self.returned.max_timeout_ms = kwargs["max_timeout_ms"]
        return self.returned


def test_activation_policy_defaults_are_deny_by_default():
    policy = SafePingActivationPolicy()
    assert not policy.enabled and not policy.allow_native_windows_backend
    assert policy.max_timeout_ms == 2000 and policy.max_attempts == 1
    assert policy.require_explicit_real_execution and policy.require_ip_literal


def test_factory_default_returns_none():
    assert build() is None


def test_policy_and_factory_are_frozen():
    with pytest.raises(FrozenInstanceError):
        SafePingActivationPolicy().enabled = True
    with pytest.raises(FrozenInstanceError):
        SafePingBackendFactory().activation_policy = activation_policy()


@pytest.mark.parametrize("field", [
    "enabled", "allow_native_windows_backend", "require_explicit_real_execution",
    "require_ip_literal",
])
@pytest.mark.parametrize("value", [None, 0, 1, "true", object()])
def test_boolean_fields_require_actual_booleans(field, value):
    with pytest.raises(ValueError):
        SafePingActivationPolicy(**{field: value})


@pytest.mark.parametrize("timeout", [-1, 0, 5001, True, 1.5, "2000", None])
def test_activation_timeout_ceiling_is_bounded(timeout):
    with pytest.raises(ValueError):
        SafePingActivationPolicy(max_timeout_ms=timeout)


@pytest.mark.parametrize("attempts", [-1, 0, 2, 3, True, 1.5, "1", None])
def test_activation_policy_never_allows_retry(attempts):
    with pytest.raises(ValueError):
        SafePingActivationPolicy(max_attempts=attempts)


@pytest.mark.parametrize("enabled,native", [
    (False, False), (False, True), (True, False),
])
def test_partial_activation_never_builds_backend(enabled, native):
    factory = SafePingBackendFactory(
        SafePingActivationPolicy(enabled=enabled, allow_native_windows_backend=native)
    )
    assert build(factory) is None


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"allow_ping": False}, {"allow_real_probe": False},
])
def test_network_policy_gates_fail_closed(changes):
    factory = SafePingBackendFactory(activation_policy())
    assert build(factory, policy=network_policy(**changes)) is None


@pytest.mark.parametrize("explicit", [False, None, 0, 1, "true", object()])
def test_real_execution_must_be_explicit_boolean_true(explicit):
    assert build(SafePingBackendFactory(activation_policy()), explicit=explicit) is None


@pytest.mark.parametrize("field", ["require_explicit_real_execution", "require_ip_literal"])
def test_required_safety_flags_cannot_be_disabled_for_activation(field):
    configured = activation_policy(**{field: False})
    assert build(SafePingBackendFactory(configured)) is None


@pytest.mark.parametrize("probe_type", [
    NetworkProbeType.TCP_PORT_CHECK, "PING", "TCP_PORT_CHECK", None, 1, object(),
])
def test_factory_only_builds_for_exact_ping_enum(probe_type):
    assert build(SafePingBackendFactory(activation_policy()), probe_type=probe_type) is None


@pytest.mark.parametrize("timeout", [-1, 0, 5001, True, 1.5, "1000", None])
def test_invalid_or_network_excessive_request_timeout_blocks(timeout):
    assert build(SafePingBackendFactory(activation_policy()), timeout=timeout) is None


@pytest.mark.parametrize("attempts", [-1, 0, 2, 3, True, 1.5, "1", None])
def test_attempts_other_than_one_block(attempts):
    assert build(SafePingBackendFactory(activation_policy()), attempts=attempts) is None


@pytest.mark.parametrize("requested,network_max,activation_max,expected", [
    (requested, network_max, activation_max, min(requested, network_max, activation_max, 5000))
    for requested in (1, 500, 1000, 2000, 3000, 5000)
    for network_max in (1000, 3000, 5000)
    for activation_max in (500, 2000, 5000)
    if requested <= network_max
])
def test_effective_timeout_is_never_increased(
    monkeypatch, requested, network_max, activation_max, expected
):
    constructor = ConstructorSpy()
    monkeypatch.setattr(activation_module, "SafePingBackend", constructor)
    factory = SafePingBackendFactory(activation_policy(max_timeout_ms=activation_max))
    backend = build(
        factory,
        policy=network_policy(
            default_timeout_ms=min(3000, network_max),
            max_timeout_ms=network_max,
        ),
        timeout=requested,
    )
    if sys.platform == "win32":
        assert backend is constructor.returned
        assert constructor.calls == [{"max_timeout_ms": expected}]
        assert expected <= requested
    else:
        assert backend is None and constructor.calls == []


def test_complete_combination_builds_only_on_actual_windows(monkeypatch):
    constructor = ConstructorSpy()
    monkeypatch.setattr(activation_module, "SafePingBackend", constructor)
    backend = build(SafePingBackendFactory(activation_policy()))
    assert (backend is constructor.returned) is (sys.platform == "win32")
    assert len(constructor.calls) == int(sys.platform == "win32")


@pytest.mark.skipif(sys.platform == "win32", reason="requires the actual non-Windows host")
def test_actual_non_windows_host_fails_closed_without_construction(monkeypatch):
    constructor = ConstructorSpy()
    monkeypatch.setattr(activation_module, "SafePingBackend", constructor)
    assert build(SafePingBackendFactory(activation_policy())) is None
    assert constructor.calls == []


def test_internal_constructor_exception_fails_closed_without_sensitive_error(monkeypatch):
    constructor = ConstructorSpy(error=RuntimeError("secret C:/private stack"))
    monkeypatch.setattr(activation_module, "SafePingBackend", constructor)
    assert build(SafePingBackendFactory(activation_policy())) is None


def test_factory_does_not_mutate_network_policy(monkeypatch):
    configured = network_policy()
    original = deepcopy(configured)
    monkeypatch.setattr(activation_module, "SafePingBackend", ConstructorSpy())
    build(SafePingBackendFactory(activation_policy()), policy=configured)
    assert configured == original


def test_factory_instances_are_independent():
    first = SafePingBackendFactory()
    second = SafePingBackendFactory(activation_policy())
    assert first is not second and first.activation_policy is not second.activation_policy
    assert not first.activation_policy.enabled and second.activation_policy.enabled


def test_factory_construction_never_calls_ping(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(activation_module, "SafePingBackend", ConstructorSpy(backend))
    build(SafePingBackendFactory(activation_policy()))
    assert backend.calls == []


def test_dispatcher_default_behavior_keeps_adapter_backend_none():
    configured = network_policy()
    dispatcher = NetworkProbeDispatcher(configured)
    assert dispatcher.safe_ping_backend_factory is None
    assert dispatcher.ping_adapter.backend is None


def test_dispatcher_dry_run_never_asks_factory_for_native_backend(monkeypatch):
    constructor = ConstructorSpy()
    monkeypatch.setattr(activation_module, "SafePingBackend", constructor)
    configured = network_policy()
    dispatcher = NetworkProbeDispatcher(
        configured,
        SafePingAdapter(configured),
        SafePingBackendFactory(activation_policy()),
    )
    result = dispatcher.dispatch(request(dry_run=True), 10)
    assert result.success and constructor.calls == []
    assert dispatcher.ping_adapter.backend is None


def test_dispatcher_real_execution_uses_explicitly_activated_fake_backend(monkeypatch):
    backend = FakeBackend()
    constructor = ConstructorSpy(backend)
    monkeypatch.setattr(activation_module, "SafePingBackend", constructor)
    configured = network_policy()
    dispatcher = NetworkProbeDispatcher(
        configured,
        SafePingAdapter(configured),
        SafePingBackendFactory(activation_policy(max_timeout_ms=500)),
    )
    result = dispatcher.dispatch(request(dry_run=False, timeout=1000), 10)
    if sys.platform == "win32":
        assert result.success and backend.calls == [(HOST, 1000)]
        assert constructor.calls == [{"max_timeout_ms": 500}]
    else:
        assert not result.success and backend.calls == [] and constructor.calls == []
    assert dispatcher.ping_adapter.backend is None


def test_dispatcher_real_execution_without_activation_stays_unavailable():
    configured = network_policy()
    result = NetworkProbeDispatcher(configured).dispatch(request(dry_run=False), 10)
    assert not result.success
    assert result.result.message == "Backend seguro de ping indisponível."


def test_dispatcher_never_activates_tcp_port_backend(monkeypatch):
    constructor = ConstructorSpy()
    monkeypatch.setattr(activation_module, "SafePingBackend", constructor)
    configured = network_policy(allow_tcp_port_check=True, allowed_ports=(443,))
    dispatcher = NetworkProbeDispatcher(
        configured,
        SafePingAdapter(configured),
        SafePingBackendFactory(activation_policy()),
    )
    result = dispatcher.dispatch(
        request(probe_type=NetworkProbeType.TCP_PORT_CHECK, port=443), 10
    )
    assert not result.success and constructor.calls == []


@pytest.mark.parametrize("forbidden", [
    "subprocess", "os", "socket", "requests", "httpx", "urllib", "threading",
    "multiprocessing", "asyncio",
])
def test_activation_module_has_no_forbidden_imports(forbidden):
    tree = ast.parse(ACTIVATION_FILE.read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert all(name != forbidden and not name.startswith(forbidden + ".") for name in imports)


@pytest.mark.parametrize("forbidden", [
    "environ", "registry", "open(", "pathlib", "powershell", "cmd.exe", "ping.exe",
    "sleep(", "getaddrinfo", "gethostbyname", "connect(", "send(", "retry",
])
def test_activation_module_has_no_io_execution_or_secret_source(forbidden):
    assert forbidden not in ACTIVATION_FILE.read_text(encoding="utf-8").casefold()


@pytest.mark.parametrize("name", ["SafePingActivationPolicy", "SafePingBackendFactory"])
def test_public_exports(name):
    namespace = {}
    exec(f"from app.services.diagnostic_engine import {name}", namespace)
    assert namespace[name].__name__ == name


@pytest.mark.parametrize("path", [ACTIVATION_FILE, DISPATCHER_FILE, PACKAGE_FILE, HERE])
def test_files_are_utf8_without_bom(path):
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    data.decode("utf-8")
