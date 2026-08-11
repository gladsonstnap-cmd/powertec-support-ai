import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import app.services.diagnostic_engine.safe_ping_activation as activation_module
from app.services.diagnostic_engine.approval_models import ApprovalActor, ApprovalType, ApprovedActionGrant
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction, ExecutionPlan, ExecutionResult, ExecutionRisk, ExecutionStatus, ExecutionTarget,
)
from app.services.diagnostic_engine.network_probe_audit import NetworkProbeAuditEventType
from app.services.diagnostic_engine.network_probe_dispatcher import NetworkProbeDispatcher
from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeResult, NetworkProbeState, NetworkProbeType,
)
from app.services.diagnostic_engine.network_probe_policy import NetworkProbePolicy
from app.services.diagnostic_engine.network_probe_rate_limit import (
    NetworkProbeRateLimitBlockReason, NetworkProbeRateLimiter,
    NetworkProbeRateLimitPolicy, NetworkProbeRateLimitResult,
)
from app.services.diagnostic_engine.network_probe_validator import NetworkProbeValidator
from app.services.diagnostic_engine.safe_ping_activation import (
    SafePingActivationPolicy, SafePingBackendFactory,
)
from app.services.diagnostic_engine.safe_ping_adapter import PingBackendResult, SafePingAdapter
from app.services.diagnostic_engine.session_engine import DiagnosticSessionEngine
from app.services.diagnostic_engine.session_models import DiagnosticSession, DiagnosticSessionStatus


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ENGINE_FILE = ROOT / "app/services/diagnostic_engine/session_engine.py"
ACTIVATION_FILE = ENGINE_FILE.with_name("safe_ping_activation.py")
DISPATCHER_FILE = ENGINE_FILE.with_name("network_probe_dispatcher.py")
ADAPTER_FILE = ENGINE_FILE.with_name("safe_ping_adapter.py")
HOST = "192.0.2.10"
SECOND_HOST = "192.0.2.11"


class FakeBackend:
    def __init__(self, result=None, error=None, hard_ceiling=5000):
        self.result = result or PingBackendResult(success=True, latency_ms=1, remote_ip=HOST)
        self.error = error
        self.hard_ceiling = hard_ceiling
        self.calls = []

    def ping(self, *, host, timeout_ms):
        self.calls.append((host, min(timeout_ms, self.hard_ceiling)))
        if self.error is not None:
            raise self.error
        return self.result


class FakeFactory(SafePingBackendFactory):
    def __init__(self, returned=None, error=None):
        super().__init__(SafePingActivationPolicy(enabled=True, allow_native_windows_backend=True))
        object.__setattr__(self, "returned", returned)
        object.__setattr__(self, "error", error)
        object.__setattr__(self, "calls", [])

    def build(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.returned


class FakeLimiter:
    def __init__(self, returned):
        self.returned = returned
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return self.returned


def action(**changes):
    values = dict(
        action_id="action-1", action_name="ping_host", title="Ping",
        description="Single-host ping", target=ExecutionTarget.NETWORK,
        status=ExecutionStatus.READY, risk=ExecutionRisk.LOW, parameters=(),
        timeout_seconds=5, requires_confirmation=True, requires_human=False,
        metadata={"action_kind": "read_only", "execution_plan_id": "plan-1"},
    )
    values.update(changes)
    return ExecutionAction(**values)


def grant(selected=None, **changes):
    selected = selected or action()
    values = dict(
        grant_id="grant-1", approval_id="approval-1", execution_plan_id="plan-1",
        action_id=selected.action_id, action_snapshot=selected,
        approved_by=ApprovalActor("actor", ApprovalType.USER_CONFIRMATION),
        approved_at_monotonic=1, expires_at_monotonic=1000,
        single_use=True, used=False, metadata={"session_id": "session-1"},
    )
    values.update(changes)
    return ApprovedActionGrant(**values)


def session(selected=None, approved=None, **changes):
    selected = selected or action()
    plan = ExecutionPlan("plan-1", ExecutionStatus.READY, (selected,), selected.action_id)
    values = dict(
        session_id="session-1", status=DiagnosticSessionStatus.READY_FOR_ACTION,
        original_message="Network issue", last_message="Network issue",
        execution_plan=plan, execution_result=ExecutionResult(True, plan, selected),
        approval_grants=((approved or grant(selected)),),
    )
    values.update(changes)
    return DiagnosticSession(**values)


def network_policy(**changes):
    values = dict(
        enabled=True, allow_ping=True, allow_real_probe=True,
        allow_private_addresses=True, allowed_hosts=(HOST, SECOND_HOST,),
    )
    values.update(changes)
    return NetworkProbePolicy(**values)


def rate_policy(**changes):
    values = dict(
        max_probes_per_session=20, max_probes_per_target=10,
        minimum_interval_ms=0, minimum_same_target_interval_ms=0,
    )
    values.update(changes)
    return NetworkProbeRateLimitPolicy(**values)


def engine(factory=None, backend=None, *, policy=None, limiter=None):
    configured = policy or network_policy()
    factory = factory if factory is not None else FakeFactory(backend)
    dispatcher = NetworkProbeDispatcher(
        configured, SafePingAdapter(configured), factory,
    )
    subject = DiagnosticSessionEngine(
        network_probe_validator=NetworkProbeValidator(configured),
        network_probe_dispatcher=dispatcher,
        network_probe_rate_limiter=limiter or NetworkProbeRateLimiter(rate_policy()),
    )
    return subject, factory


def build(subject, source=None, **changes):
    values = dict(
        action_id="action-1", grant_id="grant-1", probe_id="probe-1",
        request_id="request-1", probe_type=NetworkProbeType.PING, host=HOST,
        timeout_ms=1000, attempt=1, dry_run=False, created_at_monotonic=10,
    )
    values.update(changes)
    return subject.build_network_probe_request(source or session(), **values)


def run(*, factory=None, backend=None, policy=None, limiter=None, source=None,
        dispatch_at=20, **changes):
    subject, factory = engine(factory, backend, policy=policy, limiter=limiter)
    built = build(subject, source, **changes)
    if not built.session.network_probe_requests:
        return subject, factory, built, None
    dispatched = subject.dispatch_network_probe(
        built.session, probe_id=changes.get("probe_id", "probe-1"),
        now_monotonic=dispatch_at,
    )
    return subject, factory, built, dispatched


def event_types(item):
    return tuple(event.event_type for event in item.network_probe_audit_trail.events)


def test_default_dispatcher_is_fail_closed_but_dry_run_still_works():
    configured = network_policy()
    dispatcher = NetworkProbeDispatcher(configured)
    subject = DiagnosticSessionEngine(
        network_probe_validator=NetworkProbeValidator(configured),
        network_probe_dispatcher=dispatcher,
        network_probe_rate_limiter=NetworkProbeRateLimiter(rate_policy()),
    )
    dry = build(subject, dry_run=True).session
    dry_result = subject.dispatch_network_probe(dry, probe_id="probe-1", now_monotonic=20)
    assert dry_result.session.current_network_probe_result.success
    real = build(subject, probe_id="probe-2", request_id="request-2", dry_run=False).session
    real_result = subject.dispatch_network_probe(real, probe_id="probe-2", now_monotonic=20)
    assert not real_result.session.current_network_probe_result.success
    assert dispatcher.safe_ping_backend_factory is None and dispatcher.ping_adapter.backend is None


def test_dry_run_never_consults_factory_or_backend():
    backend = FakeBackend()
    factory = FakeFactory(backend)
    _, _, _, dispatched = run(factory=factory, dry_run=True)
    assert factory.calls == [] and backend.calls == []
    assert dispatched.session.current_network_probe_result.message == "Dry-run: ping validado; nenhum pacote foi enviado."


@pytest.mark.parametrize("timeout", [1, 10, 100, 250, 500, 750, 1000, 1500, 2000, 2500, 3000, 4000, 4999, 5000])
@pytest.mark.parametrize("outcome", ["success", "timeout", "failure", "exception"])
def test_explicit_fake_backend_end_to_end_outcome_matrix(timeout, outcome):
    result = {
        "success": PingBackendResult(success=True, latency_ms=1, remote_ip=HOST),
        "timeout": PingBackendResult(timed_out=True),
        "failure": PingBackendResult(),
        "exception": PingBackendResult(),
    }[outcome]
    backend = FakeBackend(result, RuntimeError("secret internal stack") if outcome == "exception" else None)
    _, factory, built, dispatched = run(backend=backend, timeout_ms=timeout)
    probe_result = dispatched.session.current_network_probe_result
    expected_state = {
        "success": NetworkProbeState.SUCCESS, "timeout": NetworkProbeState.TIMED_OUT,
        "failure": NetworkProbeState.FAILED, "exception": NetworkProbeState.FAILED,
    }[outcome]
    expected_event = {
        "success": NetworkProbeAuditEventType.PROBE_SUCCEEDED,
        "timeout": NetworkProbeAuditEventType.PROBE_TIMED_OUT,
        "failure": NetworkProbeAuditEventType.PROBE_FAILED,
        "exception": NetworkProbeAuditEventType.PROBE_FAILED,
    }[outcome]
    assert len(factory.calls) == len(backend.calls) == 1
    assert factory.calls[0]["timeout_ms"] == timeout and factory.calls[0]["attempts"] == 1
    assert backend.calls == [(HOST, timeout)]
    assert probe_result.state == expected_state and probe_result.success is (outcome == "success")
    assert event_types(dispatched.session)[-2:] == (NetworkProbeAuditEventType.DISPATCH_REQUESTED, expected_event)
    assert dispatched.session.approval_grants == built.session.approval_grants
    assert dispatched.session.status == built.session.status
    assert "secret" not in probe_result.message.casefold() and "stack" not in probe_result.message.casefold()


@pytest.mark.parametrize("enabled,native,network_enabled,ping,real", [
    (enabled, native, network_enabled, ping, real)
    for enabled in (False, True) for native in (False, True)
    for network_enabled in (False, True) for ping in (False, True)
    for real in (False, True)
])
def test_complete_activation_gate_matrix(monkeypatch, enabled, native, network_enabled, ping, real):
    created = []

    def constructor(**kwargs):
        created.append(kwargs)
        return FakeBackend()

    monkeypatch.setattr(activation_module, "SafePingBackend", constructor)
    factory = SafePingBackendFactory(SafePingActivationPolicy(
        enabled=enabled, allow_native_windows_backend=native,
    ))
    configured = network_policy(enabled=network_enabled, allow_ping=ping, allow_real_probe=real)
    backend = factory.build(
        network_probe_policy=configured, explicit_real_execution=True,
        probe_type=NetworkProbeType.PING, timeout_ms=1000, attempts=1,
    )
    expected = enabled and native and network_enabled and ping and real
    assert bool(backend) is expected
    assert len(created) == int(expected)


@pytest.mark.parametrize("explicit,probe_type,timeout,attempt", [
    (False, NetworkProbeType.PING, 1000, 1),
    (None, NetworkProbeType.PING, 1000, 1),
    (True, NetworkProbeType.TCP_PORT_CHECK, 1000, 1),
    (True, NetworkProbeType.PING, 0, 1),
    (True, NetworkProbeType.PING, -1, 1),
    (True, NetworkProbeType.PING, True, 1),
    (True, NetworkProbeType.PING, 1000, 0),
    (True, NetworkProbeType.PING, 1000, 2),
    (True, NetworkProbeType.PING, 1000, True),
])
def test_non_policy_factory_gates_fail_closed(explicit, probe_type, timeout, attempt):
    factory = SafePingBackendFactory(SafePingActivationPolicy(
        enabled=True, allow_native_windows_backend=True,
    ))
    assert factory.build(
        network_probe_policy=network_policy(), explicit_real_execution=explicit,
        probe_type=probe_type, timeout_ms=timeout, attempts=attempt,
    ) is None


@pytest.mark.parametrize("host,allowed,policy_changes", [
    (HOST, True, {}), (SECOND_HOST, True, {}), ("192.0.2.12", False, {}),
    ("127.0.0.1", False, {"allowed_hosts": ("127.0.0.1",)}),
    ("169.254.1.1", False, {"allowed_hosts": ("169.254.1.1",)}),
    ("224.0.0.1", False, {"allowed_hosts": ("224.0.0.1",)}),
    ("192.0.2.0/24", False, {}), ("192.0.2.1-20", False, {}),
    ("192.0.2.*", False, {}), ("a,b", False, {}),
    ("host.invalid", False, {"allowed_hosts": ("host.invalid",)}),
])
def test_host_validation_remains_before_factory(host, allowed, policy_changes):
    backend = FakeBackend()
    factory = FakeFactory(backend)
    _, _, built, dispatched = run(
        factory=factory, policy=network_policy(**policy_changes), host=host,
    )
    assert bool(built.session.network_probe_requests) is allowed
    assert len(factory.calls) == int(allowed) and len(backend.calls) == int(allowed)
    assert (dispatched is not None) is allowed


@pytest.mark.parametrize("requested,activation_max,hard_ceiling,expected", [
    (requested, activation_max, hard_ceiling, min(requested, hard_ceiling))
    for requested in (1, 100, 500, 1000, 2000, 3000, 5000)
    for activation_max in (500, 2000, 5000)
    for hard_ceiling in (250, 1000, 5000)
])
def test_timeout_path_never_increases_value(requested, activation_max, hard_ceiling, expected):
    backend = FakeBackend(hard_ceiling=hard_ceiling)
    factory = FakeFactory(backend)
    _, _, _, dispatched = run(factory=factory, backend=backend, timeout_ms=requested)
    assert factory.calls[0]["timeout_ms"] == requested
    assert backend.calls[0][1] == expected and expected <= requested
    assert dispatched.session.current_network_probe_request.timeout_ms == requested


@pytest.mark.parametrize("attempt", [0, 2, 3, 10, True, 1.5, "1", None])
def test_invalid_attempt_never_reaches_factory_or_backend(attempt):
    backend = FakeBackend()
    factory = FakeFactory(backend)
    _, _, built, dispatched = run(factory=factory, attempt=attempt)
    assert built.session.network_probe_requests == () and dispatched is None
    assert factory.calls == [] and backend.calls == []


@pytest.mark.parametrize("reason,event_type", [
    (NetworkProbeRateLimitBlockReason.SESSION_LIMIT_REACHED, NetworkProbeAuditEventType.SESSION_LIMIT_REACHED),
    (NetworkProbeRateLimitBlockReason.TARGET_LIMIT_REACHED, NetworkProbeAuditEventType.RATE_LIMITED),
    (NetworkProbeRateLimitBlockReason.GLOBAL_COOLDOWN, NetworkProbeAuditEventType.COOLDOWN_BLOCKED),
    (NetworkProbeRateLimitBlockReason.TARGET_COOLDOWN, NetworkProbeAuditEventType.COOLDOWN_BLOCKED),
    (NetworkProbeRateLimitBlockReason.DUPLICATE_PENDING_REQUEST, NetworkProbeAuditEventType.DUPLICATE_BLOCKED),
    (NetworkProbeRateLimitBlockReason.DUPLICATE_INFLIGHT_PROBE, NetworkProbeAuditEventType.DUPLICATE_BLOCKED),
])
@pytest.mark.parametrize("now", [20, 21, 50, 100])
def test_rate_limiter_blocks_before_factory(reason, event_type, now):
    limiter = FakeLimiter(NetworkProbeRateLimitResult(False, reason, "blocked"))
    backend = FakeBackend()
    factory = FakeFactory(backend)
    _, _, _, dispatched = run(factory=factory, limiter=limiter, dispatch_at=now)
    assert len(limiter.calls) == 1 and factory.calls == [] and backend.calls == []
    assert event_types(dispatched.session)[-1] == event_type
    assert NetworkProbeAuditEventType.DISPATCH_REQUESTED not in event_types(dispatched.session)


@pytest.mark.parametrize("host", ["bad host", "*", "192.0.2.0/24", "192.0.2.12"])
def test_validator_blocks_before_limiter_dispatcher_and_factory(host):
    limiter = FakeLimiter(NetworkProbeRateLimitResult(True))
    factory = FakeFactory(FakeBackend())
    _, _, built, dispatched = run(factory=factory, limiter=limiter, host=host)
    assert built.session.network_probe_requests == () and dispatched is None
    assert limiter.calls == [] and factory.calls == []


@pytest.mark.parametrize("mode", ["none", "exception", "invalid"])
def test_factory_failure_is_controlled_and_does_not_leak(mode):
    factory = FakeFactory(
        returned=None if mode == "none" else object(),
        error=RuntimeError("secret C:/private stack") if mode == "exception" else None,
    )
    _, _, _, dispatched = run(factory=factory)
    result = dispatched.session.current_network_probe_result
    assert not result.success and result.state == NetworkProbeState.FAILED
    assert "secret" not in result.message.casefold() and "private" not in repr(dispatched.session).casefold()
    assert event_types(dispatched.session)[-1] == NetworkProbeAuditEventType.PROBE_FAILED


def test_policy_objects_and_previous_snapshots_remain_immutable():
    configured = network_policy()
    activation = SafePingActivationPolicy(enabled=True, allow_native_windows_backend=True)
    limits = rate_policy()
    factory = FakeFactory(FakeBackend())
    subject, _ = engine(factory, policy=configured, limiter=NetworkProbeRateLimiter(limits))
    source = session()
    originals = deepcopy((source, source.execution_plan.actions[0], source.approval_grants[0], configured, activation, limits))
    built = build(subject, source)
    old_trail = deepcopy(built.session.network_probe_audit_trail)
    dispatched = subject.dispatch_network_probe(built.session, probe_id="probe-1", now_monotonic=20)
    assert (source, source.execution_plan.actions[0], source.approval_grants[0], configured, activation, limits) == originals
    assert built.session.network_probe_audit_trail == old_trail
    with pytest.raises(FrozenInstanceError):
        dispatched.session.current_network_probe_request.dry_run = True


def test_restart_clears_histories_without_factory_call():
    backend = FakeBackend()
    subject, factory = engine(backend=backend)
    completed = subject.dispatch_network_probe(build(subject).session, probe_id="probe-1", now_monotonic=20).session
    before = len(factory.calls)
    restarted = subject.restart_session(completed, "reiniciar").session
    assert restarted.network_probe_requests == restarted.network_probe_results == ()
    assert restarted.network_probe_dispatch_results == () and restarted.network_probe_audit_trail.events == ()
    assert len(factory.calls) == before


@pytest.mark.parametrize("command", ["status", "cancelar", "atendente", "ajuda", "help"])
def test_commands_never_call_factory_or_create_probe(command):
    subject, factory = engine(backend=FakeBackend())
    turned = subject.continue_session(session(), command).session
    assert factory.calls == [] and turned.network_probe_requests == ()
    assert turned.network_probe_audit_trail.events == ()


def test_tcp_port_check_stays_blocked_without_factory_or_backend():
    backend = FakeBackend()
    factory = FakeFactory(backend)
    configured = network_policy(allow_tcp_port_check=True, allowed_ports=(443,))
    _, _, built, dispatched = run(
        factory=factory, policy=configured,
        probe_type=NetworkProbeType.TCP_PORT_CHECK, port=443,
    )
    assert built.session.network_probe_requests == () and dispatched is None
    assert factory.calls == [] and backend.calls == []


@pytest.mark.parametrize("private", [
    "username", "hostname", "environment", "mac", "routes", "dns", "gateway",
    "command_line", "handles", "credentials", "tokens", "c:/private",
])
@pytest.mark.parametrize("outcome", ["success", "timeout", "failure", "exception"])
def test_privacy_matrix(private, outcome):
    result = {
        "success": PingBackendResult(success=True, latency_ms=1, remote_ip=HOST),
        "timeout": PingBackendResult(timed_out=True),
        "failure": PingBackendResult(), "exception": PingBackendResult(),
    }[outcome]
    backend = FakeBackend(result, RuntimeError("secret C:/private") if outcome == "exception" else None)
    _, _, _, dispatched = run(backend=backend)
    assert private not in repr(dispatched.session).casefold()


@pytest.mark.parametrize("path", [HERE, DISPATCHER_FILE])
@pytest.mark.parametrize("forbidden", [
    "subprocess", "os.system", "powershell", "cmd.exe", "ping.exe", "socket",
    "requests", "httpx", "urllib", "getaddrinfo", "gethostbyname", "nmap",
    "masscan", "sleep", "threading", "multiprocessing", "asyncio",
])
def test_static_security_has_no_new_execution_path(path, forbidden):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {alias.name.casefold() for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.casefold() for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    calls = {ast.unparse(node.func).casefold() for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert forbidden not in imports | calls


@pytest.mark.parametrize("path", [HERE, DISPATCHER_FILE])
def test_modified_files_are_utf8_without_bom(path):
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    data.decode("utf-8")
