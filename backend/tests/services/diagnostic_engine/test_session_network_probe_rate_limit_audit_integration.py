import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.services.diagnostic_engine.approval_models import ApprovalActor, ApprovalType, ApprovedActionGrant
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction, ExecutionPlan, ExecutionResult, ExecutionRisk, ExecutionStatus, ExecutionTarget,
)
from app.services.diagnostic_engine.network_probe_audit import NetworkProbeAuditEventType, NetworkProbeAuditTrail
from app.services.diagnostic_engine.network_probe_dispatcher import NetworkProbeDispatchResult
from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeBlockReason, NetworkProbeRequest, NetworkProbeResult, NetworkProbeState,
    NetworkProbeTarget, NetworkProbeType,
)
from app.services.diagnostic_engine.network_probe_policy import NetworkProbePolicy
from app.services.diagnostic_engine.network_probe_rate_limit import (
    NetworkProbeRateLimitBlockReason, NetworkProbeRateLimiter,
    NetworkProbeRateLimitPolicy, NetworkProbeRateLimitResult,
)
from app.services.diagnostic_engine.network_probe_validator import NetworkProbeValidator
from app.services.diagnostic_engine.session_engine import DiagnosticSessionEngine
from app.services.diagnostic_engine.session_models import DiagnosticSession, DiagnosticSessionStatus


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ENGINE_FILE = ROOT / "app/services/diagnostic_engine/session_engine.py"
MODELS_FILE = ENGINE_FILE.with_name("session_models.py")
HOST = "192.0.2.10"


def action():
    return ExecutionAction(
        action_id="action-1", action_name="ping_host", title="Ping", description="Safe ping",
        target=ExecutionTarget.NETWORK, status=ExecutionStatus.READY, risk=ExecutionRisk.LOW,
        parameters=(), timeout_seconds=5, requires_confirmation=True, requires_human=False,
        metadata={"action_kind": "read_only", "execution_plan_id": "plan-1"},
    )


def grant(selected):
    return ApprovedActionGrant(
        grant_id="grant-1", approval_id="approval-1", execution_plan_id="plan-1",
        action_id=selected.action_id, action_snapshot=selected,
        approved_by=ApprovalActor("actor-1", ApprovalType.USER_CONFIRMATION),
        approved_at_monotonic=1, expires_at_monotonic=1000, single_use=True,
        metadata={"session_id": "session-1"},
    )


def source(**changes):
    selected = action()
    plan = ExecutionPlan("plan-1", ExecutionStatus.READY, (selected,), selected.action_id)
    values = dict(
        session_id="session-1", status=DiagnosticSessionStatus.READY_FOR_ACTION,
        original_message="Network issue", last_message="Network issue", execution_plan=plan,
        execution_result=ExecutionResult(True, plan, selected), approval_grants=(grant(selected),),
    )
    values.update(changes)
    return DiagnosticSession(**values)


def probe_policy(**changes):
    values = dict(enabled=True, allow_ping=True, allow_private_addresses=True, allowed_hosts=(HOST, "192.0.2.11"))
    values.update(changes)
    return NetworkProbePolicy(**values)


class SpyLimiter:
    def __init__(self, result=None, error=None, order=None):
        self.result = result or NetworkProbeRateLimitResult(True)
        self.error = error
        self.calls = []
        self.order = order

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        if self.order is not None:
            self.order.append("limiter")
        if self.error is not None:
            raise self.error
        return self.result


class SpyDispatcher:
    def __init__(self, result=None, error=None, order=None):
        self.result = result
        self.error = error
        self.calls = []
        self.order = order
        self.policy = None

    def dispatch(self, request, now):
        self.calls.append((request, now))
        if self.order is not None:
            self.order.append("dispatcher")
        if self.error is not None:
            raise self.error
        return self.result


def engine(*, limiter=None, dispatcher=None, rate_policy=None):
    policy = probe_policy()
    return DiagnosticSessionEngine(
        network_probe_validator=NetworkProbeValidator(policy),
        network_probe_dispatcher=dispatcher or __import__(
            "app.services.diagnostic_engine.network_probe_dispatcher", fromlist=["NetworkProbeDispatcher"]
        ).NetworkProbeDispatcher(policy),
        network_probe_rate_limiter=limiter or NetworkProbeRateLimiter(
            rate_policy or NetworkProbeRateLimitPolicy(minimum_interval_ms=0, minimum_same_target_interval_ms=0)
        ),
    )


def build(subject=None, session=None, **changes):
    values = dict(
        action_id="action-1", grant_id="grant-1", probe_id="probe-1", request_id="request-1",
        probe_type=NetworkProbeType.PING, host=HOST, created_at_monotonic=10,
    )
    values.update(changes)
    return (subject or engine()).build_network_probe_request(session or source(), **values)


def prepared(subject=None, **changes):
    subject = subject or engine()
    return subject, build(subject, **changes).session


def dispatch_result(state=NetworkProbeState.SUCCESS, *, with_result=True):
    if not with_result:
        return NetworkProbeDispatchResult(False, NetworkProbeType.PING, errors=("blocked",))
    result = NetworkProbeResult(
        "probe-1", state, success=state == NetworkProbeState.SUCCESS,
        block_reason=NetworkProbeBlockReason.VALIDATION_FAILED if state == NetworkProbeState.BLOCKED else None,
        message="result", started_at_monotonic=20, finished_at_monotonic=20,
    )
    return NetworkProbeDispatchResult(
        success=result.success, probe_type=NetworkProbeType.PING, result=result,
        adapter_name="Spy", errors=() if result.success else ("controlled",),
    )


def event_types(session):
    return tuple(item.event_type for item in session.network_probe_audit_trail.events)


def test_old_session_constructor_gets_empty_session_bound_trail():
    item = DiagnosticSession("old", DiagnosticSessionStatus.NEW, "x", "x")
    assert item.network_probe_audit_trail == NetworkProbeAuditTrail("old")


def test_trail_must_belong_to_session():
    with pytest.raises(ValueError, match="belong"):
        DiagnosticSession("one", DiagnosticSessionStatus.NEW, "x", "x", network_probe_audit_trail=NetworkProbeAuditTrail("two"))


def test_default_and_injected_rate_limiter_dependencies():
    assert isinstance(DiagnosticSessionEngine().network_probe_rate_limiter, NetworkProbeRateLimiter)
    spy = SpyLimiter()
    assert engine(limiter=spy).network_probe_rate_limiter is spy


def test_network_and_rate_policies_remain_independent():
    subject = engine(rate_policy=NetworkProbeRateLimitPolicy(max_probes_per_session=2, minimum_interval_ms=0, minimum_same_target_interval_ms=0))
    assert subject.network_probe_validator.policy.max_probes_per_session == 10
    assert subject.network_probe_rate_limiter.policy.max_probes_per_session == 2


def test_valid_build_records_request_then_validation_events():
    turned = build().session
    assert event_types(turned) == (
        NetworkProbeAuditEventType.REQUEST_CREATED,
        NetworkProbeAuditEventType.VALIDATION_PASSED,
    )


@pytest.mark.parametrize("probe_id,request_id,created", [
    (f"probe-{index}", f"request-{index}", float(index)) for index in range(1, 41)
])
def test_request_audit_preserves_ids_time_and_session(probe_id, request_id, created):
    turned = build(probe_id=probe_id, request_id=request_id, created_at_monotonic=created).session
    assert all(item.probe_id == probe_id and item.request_id == request_id for item in turned.network_probe_audit_trail.events)
    assert all(item.session_id == "session-1" and item.timestamp_monotonic == created for item in turned.network_probe_audit_trail.events)
    assert len({item.event_id for item in turned.network_probe_audit_trail.events}) == 2


@pytest.mark.parametrize("host", ["bad host", "*", "192.0.2.0/24", "192.0.2.12"])
def test_validation_block_never_stores_or_dispatches(host):
    dispatcher = SpyDispatcher()
    turned = build(engine(dispatcher=dispatcher), host=host).session
    assert turned.network_probe_requests == () and dispatcher.calls == []
    if host == "192.0.2.12":
        assert event_types(turned) == (NetworkProbeAuditEventType.VALIDATION_BLOCKED,)


def test_limiter_runs_before_dispatcher_and_receives_exact_snapshots():
    order = []
    limiter = SpyLimiter(order=order)
    dispatcher = SpyDispatcher(dispatch_result(), order=order)
    subject, session = prepared(engine(limiter=limiter, dispatcher=dispatcher))
    request = session.network_probe_requests[0]
    turned = subject.dispatch_network_probe(session, probe_id=request.probe_id, now_monotonic=20)
    assert order == ["limiter", "dispatcher"]
    assert limiter.calls == [dict(
        request=request, existing_requests=(), existing_results=session.network_probe_results,
        audit_trail=session.network_probe_audit_trail, now_monotonic=20,
    )]
    assert turned.session.network_probe_results[-1].probe_id == request.probe_id


@pytest.mark.parametrize("reason,event_type", [
    (NetworkProbeRateLimitBlockReason.SESSION_LIMIT_REACHED, NetworkProbeAuditEventType.SESSION_LIMIT_REACHED),
    (NetworkProbeRateLimitBlockReason.TARGET_LIMIT_REACHED, NetworkProbeAuditEventType.RATE_LIMITED),
    (NetworkProbeRateLimitBlockReason.GLOBAL_COOLDOWN, NetworkProbeAuditEventType.COOLDOWN_BLOCKED),
    (NetworkProbeRateLimitBlockReason.TARGET_COOLDOWN, NetworkProbeAuditEventType.COOLDOWN_BLOCKED),
    (NetworkProbeRateLimitBlockReason.DUPLICATE_PENDING_REQUEST, NetworkProbeAuditEventType.DUPLICATE_BLOCKED),
    (NetworkProbeRateLimitBlockReason.DUPLICATE_INFLIGHT_PROBE, NetworkProbeAuditEventType.DUPLICATE_BLOCKED),
    (NetworkProbeRateLimitBlockReason.INVALID_HISTORY, NetworkProbeAuditEventType.RATE_LIMITED),
    (NetworkProbeRateLimitBlockReason.POLICY_DISABLED, NetworkProbeAuditEventType.RATE_LIMITED),
    (NetworkProbeRateLimitBlockReason.VALIDATION_FAILED, NetworkProbeAuditEventType.RATE_LIMITED),
])
@pytest.mark.parametrize("now", [20, 20.5, 21, 100])
def test_rate_blocks_before_dispatch_without_fake_result(reason, event_type, now):
    limiter = SpyLimiter(NetworkProbeRateLimitResult(False, reason, "blocked", next_allowed_at_monotonic=now + 1))
    dispatcher = SpyDispatcher()
    subject, session = prepared(engine(limiter=limiter, dispatcher=dispatcher))
    before = deepcopy(session)
    turned = subject.dispatch_network_probe(session, probe_id="probe-1", now_monotonic=now).session
    assert dispatcher.calls == [] and turned.network_probe_results == before.network_probe_results
    assert turned.network_probe_dispatch_results == before.network_probe_dispatch_results
    assert event_types(turned)[-1] == event_type
    assert turned.status == before.status and "network_probe_errors" in turned.metadata


def test_rate_limiter_exception_is_generic_and_fail_closed():
    limiter = SpyLimiter(error=RuntimeError("secret C:/private"))
    dispatcher = SpyDispatcher()
    subject, session = prepared(engine(limiter=limiter, dispatcher=dispatcher))
    turned = subject.dispatch_network_probe(session, probe_id="probe-1", now_monotonic=20).session
    assert dispatcher.calls == []
    assert turned.metadata["network_probe_errors"] == ("Falha na validação de limite do probe de rede.",)
    assert "secret" not in repr(turned.metadata).casefold()


@pytest.mark.parametrize("state,event_type", [
    (NetworkProbeState.SUCCESS, NetworkProbeAuditEventType.PROBE_SUCCEEDED),
    (NetworkProbeState.FAILED, NetworkProbeAuditEventType.PROBE_FAILED),
    (NetworkProbeState.TIMED_OUT, NetworkProbeAuditEventType.PROBE_TIMED_OUT),
    (NetworkProbeState.BLOCKED, NetworkProbeAuditEventType.DISPATCH_BLOCKED),
    (NetworkProbeState.CANCELLED, NetworkProbeAuditEventType.CANCELLED),
    (NetworkProbeState.PENDING, NetworkProbeAuditEventType.PROBE_FAILED),
    (NetworkProbeState.VALIDATED, NetworkProbeAuditEventType.PROBE_FAILED),
])
@pytest.mark.parametrize("now", [20, 21, 25, 100])
def test_dispatch_audit_matches_result_state(state, event_type, now):
    dispatcher = SpyDispatcher(dispatch_result(state))
    subject, session = prepared(engine(dispatcher=dispatcher))
    turned = subject.dispatch_network_probe(session, probe_id="probe-1", now_monotonic=now).session
    assert event_types(turned)[-2:] == (NetworkProbeAuditEventType.DISPATCH_REQUESTED, event_type)
    assert len(dispatcher.calls) == 1 and turned.status == session.status


@pytest.mark.parametrize("mode", ["missing", "exception", "invalid"])
def test_dispatch_without_valid_result_is_audited_without_fake_probe_result(mode):
    dispatcher = SpyDispatcher(
        result=NetworkProbeDispatchResult(False, NetworkProbeType.PING, errors=("controlled",)) if mode == "missing" else "invalid",
        error=RuntimeError("private") if mode == "exception" else None,
    )
    subject, session = prepared(engine(dispatcher=dispatcher))
    turned = subject.dispatch_network_probe(session, probe_id="probe-1", now_monotonic=20).session
    assert turned.network_probe_results == ()
    assert event_types(turned)[-1] == NetworkProbeAuditEventType.DISPATCH_BLOCKED


def test_audit_append_is_immutable_and_previous_session_is_unchanged():
    subject, session = prepared()
    old_trail = session.network_probe_audit_trail
    turned = subject.dispatch_network_probe(session, probe_id="probe-1", now_monotonic=20).session
    assert session.network_probe_audit_trail == old_trail
    assert turned.network_probe_audit_trail is not old_trail
    with pytest.raises(FrozenInstanceError):
        turned.network_probe_audit_trail.events = ()


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("allowed", [True, False])
@pytest.mark.parametrize("timeout", [1000, 2000, 3000, 4000, 5000])
def test_dry_run_and_real_flags_do_not_bypass_limiter(dry_run, allowed, timeout):
    limiter = SpyLimiter(
        NetworkProbeRateLimitResult(True) if allowed else NetworkProbeRateLimitResult(
            False, NetworkProbeRateLimitBlockReason.TARGET_LIMIT_REACHED, "blocked"
        )
    )
    dispatcher = SpyDispatcher(dispatch_result())
    configured = probe_policy(allow_real_probe=True)
    subject = DiagnosticSessionEngine(
        network_probe_validator=NetworkProbeValidator(configured),
        network_probe_dispatcher=dispatcher,
        network_probe_rate_limiter=limiter,
    )
    session = build(subject, dry_run=dry_run, timeout_ms=timeout).session
    subject.dispatch_network_probe(session, probe_id="probe-1", now_monotonic=20)
    assert len(limiter.calls) == 1 and len(dispatcher.calls) == int(allowed)


def test_grant_and_status_are_never_consumed_or_changed():
    subject, session = prepared()
    before = deepcopy(session.approval_grants)
    turned = subject.dispatch_network_probe(session, probe_id="probe-1", now_monotonic=20).session
    assert turned.approval_grants == before and not turned.approval_grants[0].used
    assert turned.status == session.status


def test_restart_resets_requests_results_dispatches_and_audit():
    subject, session = prepared()
    dispatched = subject.dispatch_network_probe(session, probe_id="probe-1", now_monotonic=20).session
    restarted = subject.restart_session(dispatched, "reiniciar").session
    assert restarted.network_probe_requests == restarted.network_probe_results == ()
    assert restarted.network_probe_dispatch_results == ()
    assert restarted.network_probe_audit_trail == NetworkProbeAuditTrail(restarted.session_id)


@pytest.mark.parametrize("command", ["status", "cancelar", "atendente", "ajuda", "help"])
def test_commands_do_not_add_probe_audit(command):
    subject, session = prepared()
    before = session.network_probe_audit_trail
    turned = subject.continue_session(session, command).session
    assert turned.network_probe_audit_trail == before


@pytest.mark.parametrize("key", [
    "username", "hostname", "mac", "environment", "dns", "gateway", "routes",
    "command_line", "credentials", "tokens", "stack", "traceback",
])
def test_audit_metadata_remains_privacy_bounded(key):
    subject, session = prepared()
    turned = subject.dispatch_network_probe(session, probe_id="probe-1", now_monotonic=20).session
    assert all(key not in event.metadata for event in turned.network_probe_audit_trail.events)


@pytest.mark.parametrize("forbidden", [
    "socket", "subprocess", "requests", "urllib", "ctypes", "safepingbackend",
])
def test_session_engine_has_no_direct_network_backend_import(forbidden):
    tree = ast.parse(ENGINE_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.casefold() for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.casefold() for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert all(forbidden not in name for name in imports)


@pytest.mark.parametrize("forbidden", [
    "ping.exe", "powershell", "cmd.exe", "icmpsendecho", "getaddrinfo",
    "socket.socket", "subprocess.run", "time.sleep", "check_port",
])
def test_session_integration_contains_no_execution_or_wait_primitive(forbidden):
    assert forbidden not in ENGINE_FILE.read_text(encoding="utf-8").casefold()


@pytest.mark.parametrize("path", [ENGINE_FILE, MODELS_FILE, HERE])
def test_modified_files_are_utf8_without_bom(path):
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    data.decode("utf-8")


@pytest.mark.parametrize("session_limit,target_limit,history_count", [
    (session_limit, target_limit, history_count)
    for session_limit in (2, 3, 5, 10)
    for target_limit in (1, 2, 3)
    for history_count in (0, 1, 2, 3)
])
def test_real_limiter_boundary_matrix_blocks_before_dispatch(session_limit, target_limit, history_count):
    requests = tuple(
        NetworkProbeRequest(
            probe_id=f"old-{index}", session_id="session-1", request_id=f"old-request-{index}",
            action_id=f"old-action-{index}", grant_id="grant-1", probe_type=NetworkProbeType.PING,
            target=NetworkProbeTarget(HOST), created_at_monotonic=float(index),
        ) for index in range(history_count)
    )
    policy = NetworkProbeRateLimitPolicy(
        max_probes_per_session=session_limit, max_probes_per_target=target_limit,
        minimum_interval_ms=0, minimum_same_target_interval_ms=0,
    )
    dispatcher = SpyDispatcher(dispatch_result())
    subject = engine(rate_policy=policy, dispatcher=dispatcher)
    current = build(subject, source(network_probe_requests=requests), probe_id="probe-1", request_id="request-1", created_at_monotonic=10).session
    subject.dispatch_network_probe(current, probe_id="probe-1", now_monotonic=20)
    expected_allowed = history_count < session_limit and history_count < target_limit
    assert len(dispatcher.calls) == int(expected_allowed)
