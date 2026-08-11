import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine.approval_models import ApprovalActor, ApprovalType, ApprovedActionGrant
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction, ExecutionPlan, ExecutionResult, ExecutionRisk, ExecutionStatus, ExecutionTarget,
)
from app.services.diagnostic_engine.network_probe_audit import NetworkProbeAuditEventType
from app.services.diagnostic_engine.network_probe_dispatcher import NetworkProbeDispatcher
from app.services.diagnostic_engine.network_probe_models import NetworkProbeState, NetworkProbeType
from app.services.diagnostic_engine.network_probe_policy import NetworkProbePolicy
from app.services.diagnostic_engine.network_probe_rate_limit import (
    NetworkProbeRateLimitPolicy, NetworkProbeRateLimiter,
)
from app.services.diagnostic_engine.network_probe_validator import NetworkProbeValidator
from app.services.diagnostic_engine.safe_ping_adapter import PingBackendResult, SafePingAdapter
from app.services.diagnostic_engine.session_engine import DiagnosticSessionEngine
from app.services.diagnostic_engine.session_models import DiagnosticSession, DiagnosticSessionStatus


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ENGINE_FILE = ROOT / "app/services/diagnostic_engine/session_engine.py"
DISPATCHER_FILE = ENGINE_FILE.with_name("network_probe_dispatcher.py")
ADAPTER_FILE = ENGINE_FILE.with_name("safe_ping_adapter.py")
BACKEND_FILE = ENGINE_FILE.with_name("safe_ping_backend.py")
HOST = "192.0.2.10"
SECOND_HOST = "192.0.2.11"


class FakePingBackend:
    def __init__(self, result=None, error=None):
        self.result = PingBackendResult(success=True, latency_ms=1.0, remote_ip=HOST) if result is None else result
        self.error = error
        self.calls = []

    def ping(self, *, host, timeout_ms):
        self.calls.append({"host": host, "timeout_ms": timeout_ms})
        if self.error is not None:
            raise self.error
        return self.result


def action(**changes):
    values = dict(
        action_id="action-1", action_name="ping_host", title="Ping host",
        description="Single-host diagnostic ping", target=ExecutionTarget.NETWORK,
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
        approved_by=ApprovalActor("actor-1", ApprovalType.USER_CONFIRMATION),
        approved_at_monotonic=1, expires_at_monotonic=1000, single_use=True,
        used=False, metadata={"session_id": "session-1"},
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
        allow_private_addresses=True, allowed_hosts=(HOST, SECOND_HOST),
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


def engine(backend=None, *, policy=None, limits=None):
    configured = policy or network_policy()
    backend = backend or FakePingBackend()
    adapter = SafePingAdapter(configured, backend)
    return DiagnosticSessionEngine(
        network_probe_validator=NetworkProbeValidator(configured),
        network_probe_dispatcher=NetworkProbeDispatcher(configured, adapter),
        network_probe_rate_limiter=NetworkProbeRateLimiter(limits or rate_policy()),
    ), backend


def build(subject, source=None, **changes):
    values = dict(
        action_id="action-1", grant_id="grant-1", probe_id="probe-1",
        request_id="request-1", probe_type=NetworkProbeType.PING, host=HOST,
        timeout_ms=3000, attempt=1, dry_run=True, created_at_monotonic=10,
    )
    values.update(changes)
    return subject.build_network_probe_request(source or session(), **values)


def run(*, backend=None, policy=None, limits=None, source=None, dispatch_at=20, **changes):
    subject, backend = engine(backend, policy=policy, limits=limits)
    built = build(subject, source, **changes)
    if not built.session.network_probe_requests:
        return subject, backend, built, None
    dispatched = subject.dispatch_network_probe(
        built.session, probe_id=changes.get("probe_id", "probe-1"), now_monotonic=dispatch_at,
    )
    return subject, backend, built, dispatched


def event_types(item):
    return tuple(event.event_type for event in item.network_probe_audit_trail.events)


def test_dry_run_complete_flow_skips_backend_and_preserves_message():
    _, backend, built, dispatched = run(dry_run=True)
    result = dispatched.session.current_network_probe_result
    assert backend.calls == []
    assert result.state == NetworkProbeState.SUCCESS and result.success
    assert result.message == "Dry-run: ping validado; nenhum pacote foi enviado."
    assert event_types(dispatched.session) == (
        NetworkProbeAuditEventType.REQUEST_CREATED,
        NetworkProbeAuditEventType.VALIDATION_PASSED,
        NetworkProbeAuditEventType.DISPATCH_REQUESTED,
        NetworkProbeAuditEventType.PROBE_SUCCEEDED,
    )
    assert built.session.network_probe_results == ()


@pytest.mark.parametrize("timeout", [1, 10, 100, 250, 500, 750, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 4999, 5000])
@pytest.mark.parametrize("outcome", ["success", "timeout", "failure", "exception"])
def test_fake_real_end_to_end_outcome_matrix(timeout, outcome):
    observed = {
        "success": PingBackendResult(success=True, latency_ms=1, remote_ip=HOST),
        "timeout": PingBackendResult(timed_out=True),
        "failure": PingBackendResult(),
        "exception": PingBackendResult(),
    }[outcome]
    backend = FakePingBackend(observed, RuntimeError("secret internal stack") if outcome == "exception" else None)
    _, _, built, dispatched = run(backend=backend, dry_run=False, timeout_ms=timeout)
    result = dispatched.session.current_network_probe_result
    expected_state = {
        "success": NetworkProbeState.SUCCESS,
        "timeout": NetworkProbeState.TIMED_OUT,
        "failure": NetworkProbeState.FAILED,
        "exception": NetworkProbeState.FAILED,
    }[outcome]
    expected_event = {
        "success": NetworkProbeAuditEventType.PROBE_SUCCEEDED,
        "timeout": NetworkProbeAuditEventType.PROBE_TIMED_OUT,
        "failure": NetworkProbeAuditEventType.PROBE_FAILED,
        "exception": NetworkProbeAuditEventType.PROBE_FAILED,
    }[outcome]
    assert backend.calls == [{"host": HOST, "timeout_ms": timeout}]
    assert result.state == expected_state and result.success is (outcome == "success")
    assert event_types(dispatched.session)[-2:] == (NetworkProbeAuditEventType.DISPATCH_REQUESTED, expected_event)
    assert built.session.approval_grants == dispatched.session.approval_grants
    assert dispatched.session.status == built.session.status
    assert "secret" not in result.message.casefold() and "stack" not in result.message.casefold()


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("timeout", [1, 1000, 3000, 5000])
def test_action_grant_request_and_policy_snapshots_are_immutable(dry_run, timeout):
    configured = network_policy()
    subject, backend = engine(policy=configured)
    source = session()
    originals = deepcopy((source, source.execution_plan.actions[0], source.approval_grants[0], configured))
    built = build(subject, source, dry_run=dry_run, timeout_ms=timeout)
    dispatched = subject.dispatch_network_probe(built.session, probe_id="probe-1", now_monotonic=20)
    assert (source, source.execution_plan.actions[0], source.approval_grants[0], configured) == originals
    assert not dispatched.session.approval_grants[0].used
    assert dispatched.session.execution_plan.actions[0].status == ExecutionStatus.READY
    assert len(backend.calls) == int(not dry_run)


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"allow_ping": False}, {"allow_real_probe": False},
    {"allowed_hosts": (SECOND_HOST,)}, {"allow_private_addresses": False},
])
def test_policy_denial_stops_before_backend(changes):
    configured = network_policy(**changes)
    _, backend, built, dispatched = run(policy=configured, dry_run=False)
    assert backend.calls == []
    if changes == {"allow_real_probe": False}:
        assert built.session.network_probe_requests == ()
    else:
        assert built.session.network_probe_requests == ()
    assert dispatched is None


@pytest.mark.parametrize("case", [
    "missing", "action_mismatch", "plan_mismatch", "used", "expired", "session_mismatch",
])
def test_grant_failures_stop_validator_pipeline(case):
    selected = action()
    approved = grant(selected)
    source = session(selected, approved)
    changes = {}
    if case == "missing":
        source = replace(source, approval_grants=())
        changes["grant_id"] = "missing"
    elif case == "action_mismatch":
        changes["action_id"] = "missing"
    elif case == "plan_mismatch":
        approved = grant(selected, execution_plan_id="other")
        source = session(selected, approved)
    elif case == "used":
        source = session(selected, grant(selected, used=True))
    elif case == "expired":
        source = session(selected, grant(selected, expires_at_monotonic=10))
    else:
        source = session(selected, grant(selected, metadata={"session_id": "other"}))
    _, backend, built, dispatched = run(source=source, dry_run=False, **changes)
    assert built.session.network_probe_requests == () and dispatched is None and backend.calls == []


@pytest.mark.parametrize("case", ["missing", "name", "target", "risk", "kind", "status"])
def test_action_failures_stop_all_downstream_execution(case):
    changes = {
        "name": {"action_name": "collect_event_logs"},
        "target": {"target": ExecutionTarget.WINDOWS},
        "risk": {"risk": ExecutionRisk.MEDIUM},
        "kind": {"metadata": {"action_kind": "state_changing", "execution_plan_id": "plan-1"}},
        "status": {"status": ExecutionStatus.BLOCKED},
    }.get(case, {})
    selected = action(**changes)
    source = session(selected, grant(selected))
    arguments = {"action_id": "missing"} if case == "missing" else {}
    _, backend, built, dispatched = run(source=source, dry_run=False, **arguments)
    assert built.session.network_probe_requests == () and dispatched is None and backend.calls == []


@pytest.mark.parametrize("host,allowed,extra", [
    (HOST, True, {}), (SECOND_HOST, True, {}), ("192.0.2.12", False, {}),
    ("10.0.0.1", True, {"allowed_hosts": ("10.0.0.1",), "allow_private_addresses": True}),
    ("10.0.0.1", False, {"allowed_hosts": ("10.0.0.1",), "allow_private_addresses": False}),
    ("127.0.0.1", False, {"allowed_hosts": ("127.0.0.1",)}),
    ("169.254.1.1", False, {"allowed_hosts": ("169.254.1.1",)}),
    ("224.0.0.1", False, {"allowed_hosts": ("224.0.0.1",)}),
    ("0.0.0.0", False, {"allowed_hosts": ("0.0.0.0",)}),
    ("240.0.0.1", False, {"allowed_hosts": ("240.0.0.1",)}),
    ("192.0.2.0/24", False, {}), ("192.0.2.1-20", False, {}),
    ("192.0.2.*", False, {}), ("a,b", False, {}), ("a b", False, {}),
    ("host.invalid", False, {"allowed_hosts": ("host.invalid",)}),
])
def test_host_security_matrix_never_resolves_or_expands(host, allowed, extra):
    configured = network_policy(**extra)
    _, backend, built, dispatched = run(policy=configured, host=host, dry_run=True)
    assert bool(built.session.network_probe_requests) is allowed
    assert backend.calls == []
    assert (dispatched is not None) is allowed


@pytest.mark.parametrize("reason,policy_changes,history_count,host_pattern", [
    (NetworkProbeAuditEventType.SESSION_LIMIT_REACHED, {"max_probes_per_session": 1}, 1, "different"),
    (NetworkProbeAuditEventType.RATE_LIMITED, {"max_probes_per_target": 1}, 1, "same"),
    (NetworkProbeAuditEventType.COOLDOWN_BLOCKED, {"minimum_interval_ms": 1000, "minimum_same_target_interval_ms": 3000}, 1, "different"),
    (NetworkProbeAuditEventType.COOLDOWN_BLOCKED, {"minimum_interval_ms": 0, "minimum_same_target_interval_ms": 3000, "block_duplicate_pending_request": False}, 1, "same"),
])
@pytest.mark.parametrize("dispatch_at", [10, 10.25, 10.5, 10.999])
def test_real_rate_limiter_blocks_backend_before_dispatch(reason, policy_changes, history_count, host_pattern, dispatch_at):
    subject, backend = engine(limits=rate_policy(**policy_changes))
    first = build(subject, host=SECOND_HOST if host_pattern == "different" else HOST).session
    current = build(subject, first, probe_id="probe-2", request_id="request-2", created_at_monotonic=10).session
    turned = subject.dispatch_network_probe(current, probe_id="probe-2", now_monotonic=dispatch_at).session
    assert backend.calls == [] and turned.network_probe_results == ()
    assert event_types(turned)[-1] == reason


@pytest.mark.parametrize("same_target", [False, True])
@pytest.mark.parametrize("elapsed_ms,allowed", [(0, False), (999, False), (1000, True), (1001, True), (3000, True), (3001, True)])
def test_cooldown_boundaries_without_sleep(same_target, elapsed_ms, allowed):
    interval = 3000 if same_target else 1000
    limits = rate_policy(
        minimum_interval_ms=1000,
        minimum_same_target_interval_ms=3000,
        block_duplicate_pending_request=False,
    )
    subject, backend = engine(limits=limits)
    previous_host = HOST if same_target else SECOND_HOST
    first = build(subject, host=previous_host, dry_run=False, created_at_monotonic=10).session
    current = build(subject, first, probe_id="probe-2", request_id="request-2", dry_run=False, created_at_monotonic=10 + elapsed_ms / 1000).session
    turned = subject.dispatch_network_probe(current, probe_id="probe-2", now_monotonic=10 + elapsed_ms / 1000).session
    expected = elapsed_ms >= interval
    assert bool(backend.calls) is expected
    assert expected is (allowed if not same_target else elapsed_ms >= 3000)


@pytest.mark.parametrize("state", [None, NetworkProbeState.PENDING, NetworkProbeState.VALIDATED])
def test_duplicate_pending_and_inflight_block_backend(state):
    limits = rate_policy(minimum_interval_ms=0, minimum_same_target_interval_ms=0)
    subject, backend = engine(limits=limits)
    first = build(subject).session
    if state is not None:
        from app.services.diagnostic_engine.network_probe_models import NetworkProbeResult
        first = replace(first, network_probe_results=(NetworkProbeResult("probe-1", state),))
    current = build(subject, first, probe_id="probe-2", request_id="request-2").session
    turned = subject.dispatch_network_probe(current, probe_id="probe-2", now_monotonic=20).session
    assert backend.calls == []
    assert event_types(turned)[-1] == NetworkProbeAuditEventType.DUPLICATE_BLOCKED


@pytest.mark.parametrize("timeout", [1, 2, 10, 100, 999, 1000, 2999, 3000, 4999, 5000])
def test_timeout_is_preserved_end_to_end_and_never_increased(timeout):
    _, backend, _, dispatched = run(dry_run=False, timeout_ms=timeout)
    assert backend.calls[0]["timeout_ms"] == timeout
    assert dispatched.session.current_network_probe_request.timeout_ms == timeout


@pytest.mark.parametrize("attempt", [-1, 0, 2, 3, 10, True, 1.5, "1", None])
def test_attempt_is_never_incremented_or_retried(attempt):
    _, backend, built, dispatched = run(dry_run=False, attempt=attempt)
    assert built.session.network_probe_requests == () and dispatched is None and backend.calls == []


def test_multiple_completed_probes_preserve_all_histories_and_unique_events():
    subject, backend = engine(limits=rate_policy(block_duplicate_pending_request=False))
    current = session()
    for index, host in enumerate((HOST, SECOND_HOST, HOST), 1):
        created_at = 10 + index * 10
        current = build(
            subject, current, probe_id=f"probe-{index}", request_id=f"request-{index}",
            host=host, dry_run=False, created_at_monotonic=created_at,
        ).session
        current = subject.dispatch_network_probe(current, probe_id=f"probe-{index}", now_monotonic=created_at + 1).session
    assert len(current.network_probe_requests) == 3
    assert len(current.network_probe_dispatch_results) == 3
    assert len(current.network_probe_results) == 3 and len(backend.calls) == 3
    identifiers = tuple(item.event_id for item in current.network_probe_audit_trail.events)
    assert len(identifiers) == len(set(identifiers)) == 12
    assert identifiers == tuple(sorted(identifiers, key=lambda value: int(value.rsplit(":", 1)[1])))


@pytest.mark.parametrize("index", range(1, 21))
def test_event_ids_are_deterministic_without_wall_clock(index):
    subject, _ = engine()
    probe_id = f"deterministic-probe-{index}"
    first = build(subject, probe_id=probe_id, request_id=f"request-{index}").session
    second = build(engine()[0], probe_id=probe_id, request_id=f"request-{index}").session
    expected = (f"{probe_id}:event:000000", f"{probe_id}:event:000001")
    assert tuple(item.event_id for item in first.network_probe_audit_trail.events) == expected
    assert tuple(item.event_id for item in second.network_probe_audit_trail.events) == expected


def test_restart_clears_history_without_automatic_backend_call():
    subject, backend = engine()
    completed = run(backend=backend, dry_run=False)[3].session
    before = len(backend.calls)
    restarted = subject.restart_session(completed, "reiniciar").session
    assert restarted.network_probe_requests == restarted.network_probe_results == ()
    assert restarted.network_probe_dispatch_results == () and restarted.network_probe_audit_trail.events == ()
    assert len(backend.calls) == before


@pytest.mark.parametrize("command", ["status", "cancelar", "atendente", "ajuda", "help"])
def test_commands_never_create_probe_or_call_backend(command):
    subject, backend = engine()
    source = session()
    turned = subject.continue_session(source, command).session
    assert turned.network_probe_requests == turned.network_probe_results == ()
    assert turned.network_probe_audit_trail.events == () and backend.calls == []


def test_default_adapter_has_no_backend_and_fails_closed_for_real_request():
    configured = network_policy()
    assert SafePingAdapter(configured).backend is None


def test_tcp_port_check_is_blocked_before_any_backend():
    configured = network_policy(allow_tcp_port_check=True, allowed_ports=(443,))
    _, backend, built, dispatched = run(
        policy=configured, probe_type=NetworkProbeType.TCP_PORT_CHECK, port=443, dry_run=False,
    )
    assert built.session.network_probe_requests == () and dispatched is None and backend.calls == []


@pytest.mark.parametrize("private_key", [
    "username", "hostname", "environment", "mac", "routes", "dns", "gateway",
    "command_line", "stack", "traceback", "credentials", "token",
])
@pytest.mark.parametrize("outcome", ["dry", "success", "timeout", "failure"])
def test_end_to_end_snapshots_do_not_gain_private_data(private_key, outcome):
    result = {
        "dry": PingBackendResult(success=True, latency_ms=1, remote_ip=HOST),
        "success": PingBackendResult(success=True, latency_ms=1, remote_ip=HOST),
        "timeout": PingBackendResult(timed_out=True),
        "failure": PingBackendResult(),
    }[outcome]
    _, _, _, dispatched = run(backend=FakePingBackend(result), dry_run=outcome == "dry")
    text = repr(dispatched.session).casefold()
    assert private_key not in text


@pytest.mark.parametrize("path", [ENGINE_FILE, DISPATCHER_FILE])
@pytest.mark.parametrize("forbidden", ["ctypes", "socket", "subprocess", "requests", "httpx"])
def test_session_and_dispatcher_have_no_direct_network_execution_import(path, forbidden):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert all(name != forbidden and not name.startswith(forbidden + ".") for name in imports)


@pytest.mark.parametrize("forbidden", [
    "getaddrinfo", "gethostbyname", "socket.socket", "subprocess.run", "ping.exe",
    "test-netconnection", "nmap", "masscan", "threading", "asyncio", "multiprocessing",
])
def test_new_end_to_end_test_has_no_real_traffic_scan_retry_or_concurrency(forbidden):
    tree = ast.parse(HERE.read_text(encoding="utf-8"))
    imports = {alias.name.casefold() for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.casefold() for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    calls = {ast.unparse(node.func).casefold() for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert forbidden.casefold() not in imports | calls


@pytest.mark.parametrize("path", [HERE])
def test_created_file_is_utf8_without_bom(path):
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    data.decode("utf-8")


def test_all_snapshots_are_frozen_and_previous_trail_is_unchanged():
    subject, _ = engine()
    built = build(subject).session
    prior = deepcopy(built.network_probe_audit_trail)
    dispatched = subject.dispatch_network_probe(built, probe_id="probe-1", now_monotonic=20).session
    assert built.network_probe_audit_trail == prior
    with pytest.raises(FrozenInstanceError):
        dispatched.current_network_probe_request.dry_run = False
    with pytest.raises(FrozenInstanceError):
        dispatched.network_probe_audit_trail.events = ()
