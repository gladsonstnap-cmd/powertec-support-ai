import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine.approval_models import (
    ApprovalActor,
    ApprovalType,
    ApprovedActionGrant,
)
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction,
    ExecutionPlan,
    ExecutionResult,
    ExecutionRisk,
    ExecutionStatus,
    ExecutionTarget,
)
from app.services.diagnostic_engine.network_probe_dispatcher import (
    NetworkProbeDispatcher,
    NetworkProbeDispatchResult,
)
from app.services.diagnostic_engine.network_probe_models import (
    NetworkProbeRequest,
    NetworkProbeResult,
    NetworkProbeState,
    NetworkProbeTarget,
    NetworkProbeType,
)
from app.services.diagnostic_engine.network_probe_policy import NetworkProbePolicy
from app.services.diagnostic_engine.network_probe_validator import (
    NetworkProbeValidationResult,
    NetworkProbeValidator,
)
from app.services.diagnostic_engine.session_engine import DiagnosticSessionEngine
from app.services.diagnostic_engine.session_models import DiagnosticSession, DiagnosticSessionStatus


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ENGINE_FILE = ROOT / "app/services/diagnostic_engine/session_engine.py"
MODELS_FILE = ENGINE_FILE.with_name("session_models.py")
TEST_HOST = "192.0.2.10"


def action(**changes):
    values = dict(
        action_id="action-1",
        action_name="ping_host",
        title="Ping host",
        description="Structural ping diagnostic.",
        target=ExecutionTarget.NETWORK,
        status=ExecutionStatus.READY,
        risk=ExecutionRisk.LOW,
        parameters=(),
        timeout_seconds=5,
        requires_confirmation=True,
        requires_human=False,
        metadata={"action_kind": "read_only", "execution_plan_id": "plan-1"},
    )
    values.update(changes)
    return ExecutionAction(**values)


def grant(item=None, **changes):
    selected = action() if item is None else item
    values = dict(
        grant_id="grant-1",
        approval_id="approval-1",
        execution_plan_id="plan-1",
        action_id=selected.action_id,
        action_snapshot=selected,
        approved_by=ApprovalActor("actor-1", ApprovalType.USER_CONFIRMATION),
        approved_at_monotonic=1,
        expires_at_monotonic=100,
        single_use=True,
        used=False,
        metadata={"session_id": "session-1"},
    )
    values.update(changes)
    return ApprovedActionGrant(**values)


def session(item=None, approved=None, **changes):
    selected = action() if item is None else item
    source_plan = ExecutionPlan("plan-1", ExecutionStatus.READY, (selected,), selected.action_id)
    approved = grant(selected) if approved is None else approved
    values = dict(
        session_id="session-1",
        status=DiagnosticSessionStatus.READY_FOR_ACTION,
        original_message="Network issue",
        last_message="Network issue",
        execution_plan=source_plan,
        execution_result=ExecutionResult(True, source_plan, selected),
        approval_grants=(approved,),
    )
    values.update(changes)
    return DiagnosticSession(**values)


def probe_policy(**changes):
    values = dict(
        enabled=True,
        allow_ping=True,
        allow_private_addresses=True,
        allowed_hosts=(TEST_HOST,),
    )
    values.update(changes)
    return NetworkProbePolicy(**values)


def engine(configured=None):
    configured = probe_policy() if configured is None else configured
    return DiagnosticSessionEngine(
        network_probe_validator=NetworkProbeValidator(configured),
        network_probe_dispatcher=NetworkProbeDispatcher(configured),
    )


def build(subject=None, source=None, **changes):
    values = dict(
        action_id="action-1",
        grant_id="grant-1",
        probe_id="probe-1",
        request_id="request-1",
        probe_type=NetworkProbeType.PING,
        host=TEST_HOST,
        created_at_monotonic=10,
    )
    values.update(changes)
    return (subject or engine()).build_network_probe_request(source or session(), **values)


def built(subject=None, source=None, **changes):
    subject = subject or engine()
    return subject, build(subject, source, **changes).session


def test_session_network_probe_defaults_are_empty():
    source = DiagnosticSession("id", DiagnosticSessionStatus.NEW, "error", "error")
    assert source.network_probe_requests == ()
    assert source.network_probe_results == ()
    assert source.network_probe_dispatch_results == ()
    assert source.current_network_probe_request is None
    assert source.current_network_probe_result is None
    assert source.current_network_probe_dispatch_result is None


def test_default_engine_creates_validator_and_dispatcher_with_shared_policy():
    subject = DiagnosticSessionEngine()
    assert isinstance(subject.network_probe_validator, NetworkProbeValidator)
    assert isinstance(subject.network_probe_dispatcher, NetworkProbeDispatcher)
    assert subject.network_probe_validator.policy is subject.network_probe_dispatcher.policy


def test_custom_dependencies_are_preserved():
    configured = probe_policy()
    validator = NetworkProbeValidator(configured)
    dispatcher = NetworkProbeDispatcher(configured)
    subject = DiagnosticSessionEngine(
        network_probe_validator=validator,
        network_probe_dispatcher=dispatcher,
    )
    assert subject.network_probe_validator is validator
    assert subject.network_probe_dispatcher is dispatcher


def test_one_custom_dependency_supplies_shared_policy_to_other():
    configured = probe_policy()
    validator = NetworkProbeValidator(configured)
    first = DiagnosticSessionEngine(network_probe_validator=validator)
    assert first.network_probe_dispatcher.policy is configured
    dispatcher = NetworkProbeDispatcher(configured)
    second = DiagnosticSessionEngine(network_probe_dispatcher=dispatcher)
    assert second.network_probe_validator.policy is configured


def test_incompatible_custom_policies_are_rejected():
    with pytest.raises(ValueError, match="policies must match"):
        DiagnosticSessionEngine(
            network_probe_validator=NetworkProbeValidator(probe_policy()),
            network_probe_dispatcher=NetworkProbeDispatcher(probe_policy(allow_ping=False)),
        )


def test_start_and_continue_do_not_create_probe_automatically():
    subject = DiagnosticSessionEngine()
    started = subject.start_session("Network error", session_id="session-1").session
    assert started.network_probe_requests == () and started.network_probe_dispatch_results == ()
    continued = subject.continue_session(started, "More information").session
    assert continued.network_probe_requests == () and continued.network_probe_results == ()


@pytest.mark.parametrize("command", ["status", "ajuda", "help", "atendente", "cancelar"])
def test_commands_never_create_or_dispatch_probe(command):
    subject = DiagnosticSessionEngine()
    source = subject.start_session("Network error", session_id="session-1").session
    turned = subject.continue_session(source, command).session
    assert turned.network_probe_requests == ()
    assert turned.network_probe_results == ()
    assert turned.network_probe_dispatch_results == ()


def test_valid_ping_request_is_stored_without_dispatch():
    turn = build()
    assert turn.state_changed and len(turn.session.network_probe_requests) == 1
    assert turn.session.current_network_probe_request == turn.session.network_probe_requests[0]
    assert turn.session.network_probe_results == ()
    assert turn.session.network_probe_dispatch_results == ()


@pytest.mark.parametrize("field,expected", [
    ("probe_id", "probe-1"), ("request_id", "request-1"),
    ("action_id", "action-1"), ("grant_id", "grant-1"),
    ("session_id", "session-1"), ("timeout_ms", 3000),
    ("attempt", 1), ("dry_run", True),
])
def test_built_request_preserves_expected_fields(field, expected):
    item = build().session.current_network_probe_request
    assert getattr(item, field) == expected


def test_built_request_preserves_host_and_has_no_port_or_resolution():
    item = build().session.current_network_probe_request
    assert item.target == NetworkProbeTarget(TEST_HOST)
    assert item.target.port is None and item.target.resolved_ip is None


def test_default_policy_denies_build_without_bypass():
    turn = DiagnosticSessionEngine().build_network_probe_request(
        session(), action_id="action-1", grant_id="grant-1", probe_id="probe-1",
        request_id="request-1", probe_type=NetworkProbeType.PING,
        host=TEST_HOST, created_at_monotonic=10,
    )
    assert not turn.session.network_probe_requests
    assert "network_probe_errors" in turn.session.metadata


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"allow_ping": False},
    {"enabled": False, "allow_ping": False},
])
def test_custom_policy_gates_are_not_bypassed(changes):
    assert not build(engine(probe_policy(**changes))).session.network_probe_requests


@pytest.mark.parametrize("host", [
    "192.0.2.11", "198.51.100.10", "203.0.113.10",
    "192.168.1.0/24", "192.168.1.1-254", "192.168.1.*",
    "host1,host2", "host1;host2", "host1 host2", "*",
])
def test_host_rules_are_delegated_and_fail_closed(host):
    turn = build(host=host)
    assert turn.session.network_probe_requests == ()


@pytest.mark.parametrize("port", [1, 53, 80, 443, 65535])
def test_ping_port_is_blocked_by_validator(port):
    assert build(port=port).session.network_probe_requests == ()


@pytest.mark.parametrize("action_id", ["missing", "", None])
def test_missing_action_is_blocked(action_id):
    assert build(action_id=action_id).session.network_probe_requests == ()


@pytest.mark.parametrize("grant_id", ["missing", "", None])
def test_missing_grant_is_blocked(grant_id):
    assert build(grant_id=grant_id).session.network_probe_requests == ()


@pytest.mark.parametrize("changes", [
    {"action_name": "check_port"},
    {"action_name": "unknown"},
    {"target": ExecutionTarget.WINDOWS},
    {"risk": ExecutionRisk.MEDIUM},
    {"metadata": {"action_kind": "state_changing", "execution_plan_id": "plan-1"}},
])
def test_validator_controls_action_contract(changes):
    selected = action(**changes)
    source = session(selected, grant(selected))
    assert build(source=source).session.network_probe_requests == ()


@pytest.mark.parametrize("grant_changes", [
    {"used": True},
    {"metadata": {"session_id": "other"}},
    {"expires_at_monotonic": 10},
])
def test_validator_controls_grant_contract(grant_changes):
    selected = action()
    approved = grant(selected, **grant_changes)
    source = session(selected, approved)
    assert build(source=source).session.network_probe_requests == ()


def test_action_grant_plan_and_approval_history_are_unchanged_after_build():
    source = session()
    before = deepcopy(source)
    build(source=source)
    assert source == before
    assert source.approval_grants[0].used is False


@pytest.mark.parametrize("count", [0, 1, 8, 9])
def test_explicit_session_count_under_limit_is_allowed(count):
    assert build(existing_probe_count=count).session.network_probe_requests


@pytest.mark.parametrize("count", [10, 11, 100])
def test_explicit_session_count_at_limit_is_blocked(count):
    assert not build(existing_probe_count=count).session.network_probe_requests


def test_session_history_count_is_used_when_count_omitted():
    requests = tuple(
        request_snapshot(probe_id=f"probe-{index}", request_id=f"request-{index}")
        for index in range(10)
    )
    source = session(network_probe_requests=requests)
    assert build(source=source, probe_id="new", request_id="new").session.network_probe_requests == requests


def request_snapshot(**changes):
    values = dict(
        probe_id="probe-1", session_id="session-1", request_id="request-1",
        action_id="action-1", grant_id="grant-1", probe_type=NetworkProbeType.PING,
        target=NetworkProbeTarget(TEST_HOST), timeout_ms=3000, attempt=1,
        dry_run=True, created_at_monotonic=10,
    )
    values.update(changes)
    return NetworkProbeRequest(**values)


def test_equivalent_request_is_deduplicated():
    subject, first = built()
    second = build(subject, first)
    assert not second.state_changed and second.session == first
    assert len(second.session.network_probe_requests) == 1


@pytest.mark.parametrize("changes", [
    {"probe_id": "probe-2"}, {"request_id": "request-2"},
    {"host": "192.0.2.11"}, {"timeout_ms": 1000},
    {"dry_run": False},
])
def test_distinct_request_is_not_silently_deduplicated(changes):
    configured = probe_policy(allowed_hosts=(TEST_HOST, "192.0.2.11"), allow_real_probe=True)
    subject, first = built(engine(configured))
    second = build(subject, first, **changes)
    assert len(second.session.network_probe_requests) == 2


def test_dispatch_dry_run_stores_dispatch_and_probe_results():
    subject, source = built()
    turn = subject.dispatch_network_probe(source, probe_id="probe-1", now_monotonic=20)
    assert turn.state_changed
    assert len(turn.session.network_probe_dispatch_results) == 1
    assert len(turn.session.network_probe_results) == 1
    assert turn.session.current_network_probe_dispatch_result == turn.session.network_probe_dispatch_results[-1]
    assert turn.session.current_network_probe_result == turn.session.network_probe_results[-1]
    assert turn.session.current_network_probe_result.message == "Dry-run: ping validado; nenhum pacote foi enviado."


def test_dispatch_preserves_request_and_session_status():
    subject, source = built()
    before_request = deepcopy(source.current_network_probe_request)
    before_status = source.status
    turned = subject.dispatch_network_probe(source, probe_id="probe-1", now_monotonic=20)
    assert source.current_network_probe_request == before_request
    assert turned.session.status == before_status


@pytest.mark.parametrize("probe_id", ["missing", "", None])
def test_missing_probe_request_fails_without_fake_result(probe_id):
    turn = engine().dispatch_network_probe(session(), probe_id=probe_id, now_monotonic=20)
    assert turn.session.network_probe_dispatch_results == ()
    assert turn.session.network_probe_results == ()
    assert "network_probe_errors" in turn.session.metadata


def test_real_request_without_backend_fails_controlled_and_is_recorded():
    configured = probe_policy(allow_real_probe=True)
    subject, source = built(engine(configured), dry_run=False)
    turn = subject.dispatch_network_probe(source, probe_id="probe-1", now_monotonic=20)
    assert not turn.session.current_network_probe_dispatch_result.success
    assert turn.session.current_network_probe_result.state == NetworkProbeState.FAILED
    assert turn.session.current_network_probe_result.message == "Backend seguro de ping indisponível."


def test_tcp_port_check_is_blocked_before_build_and_never_dispatched():
    configured = NetworkProbePolicy(
        enabled=True, allow_tcp_port_check=True, allow_private_addresses=True,
        allowed_hosts=(TEST_HOST,), allowed_ports=(443,),
    )
    turn = build(engine(configured), probe_type=NetworkProbeType.TCP_PORT_CHECK, port=443)
    assert turn.session.network_probe_requests == ()
    assert turn.session.network_probe_dispatch_results == ()


class FakeValidator:
    def __init__(self, returned=None, error=None, configured=None):
        self.policy = configured
        self.returned = returned
        self.error = error
        self.calls = []

    def build_request(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.returned


class FakeDispatcher:
    def __init__(self, returned=None, error=None, configured=None):
        self.policy = configured
        self.returned = returned
        self.error = error
        self.calls = []

    def dispatch(self, item, now):
        self.calls.append((item, now))
        if self.error:
            raise self.error
        return self.returned


def test_fake_validator_is_called_and_session_does_not_dispatch_implicitly():
    candidate = request_snapshot()
    fake = FakeValidator(NetworkProbeValidationResult(success=True, request=candidate, target=candidate.target))
    dispatcher = FakeDispatcher()
    subject = DiagnosticSessionEngine(network_probe_validator=fake, network_probe_dispatcher=dispatcher)
    turn = build(subject)
    assert len(fake.calls) == 1 and dispatcher.calls == []
    assert turn.session.current_network_probe_request == candidate


def test_fake_dispatcher_is_called_with_exact_stored_request():
    snapshot = NetworkProbeDispatchResult(
        success=True, probe_type=NetworkProbeType.PING,
        result=NetworkProbeResult("probe-1", NetworkProbeState.SUCCESS, success=True, message="fake"),
        adapter_name="Fake",
    )
    dispatcher = FakeDispatcher(snapshot)
    subject = DiagnosticSessionEngine(network_probe_dispatcher=dispatcher)
    source = session(network_probe_requests=(request_snapshot(),))
    turn = subject.dispatch_network_probe(source, probe_id="probe-1", now_monotonic=20)
    assert dispatcher.calls == [(source.network_probe_requests[0], 20)]
    assert turn.session.current_network_probe_dispatch_result == snapshot


@pytest.mark.parametrize("boundary", ["validator", "dispatcher"])
def test_dependency_exceptions_are_generic_without_stack_details(boundary):
    secret = RuntimeError("secret stack C:/private")
    if boundary == "validator":
        subject = DiagnosticSessionEngine(
            network_probe_validator=FakeValidator(error=secret),
            network_probe_dispatcher=FakeDispatcher(),
        )
        turn = build(subject)
    else:
        subject = DiagnosticSessionEngine(network_probe_dispatcher=FakeDispatcher(error=secret))
        turn = subject.dispatch_network_probe(
            session(network_probe_requests=(request_snapshot(),)),
            probe_id="probe-1", now_monotonic=20,
        )
    errors = tuple(turn.session.metadata["network_probe_errors"])
    assert errors == ("Falha no probe de rede.",)
    assert "secret" not in " ".join(errors).lower()


def test_dispatch_failure_without_result_is_stored_but_does_not_invent_probe_result():
    failure = NetworkProbeDispatchResult(
        success=False, probe_type=NetworkProbeType.PING, errors=("controlled",),
    )
    subject = DiagnosticSessionEngine(network_probe_dispatcher=FakeDispatcher(failure))
    source = session(network_probe_requests=(request_snapshot(),))
    turn = subject.dispatch_network_probe(source, probe_id="probe-1", now_monotonic=20)
    assert turn.session.network_probe_dispatch_results == (failure,)
    assert turn.session.network_probe_results == ()
    assert turn.session.current_network_probe_result is None


def test_multiple_explicit_requests_and_dispatches_preserve_history():
    configured = probe_policy(allowed_hosts=(TEST_HOST, "192.0.2.11"))
    subject, first = built(engine(configured))
    second = build(subject, first, probe_id="probe-2", request_id="request-2", host="192.0.2.11").session
    first_dispatch = subject.dispatch_network_probe(second, probe_id="probe-1", now_monotonic=20).session
    final = subject.dispatch_network_probe(first_dispatch, probe_id="probe-2", now_monotonic=21).session
    assert len(final.network_probe_requests) == 2
    assert len(final.network_probe_dispatch_results) == 2
    assert len(final.network_probe_results) == 2


def test_status_cancel_and_restart_history_rules():
    subject, source = built()
    dispatched = subject.dispatch_network_probe(source, probe_id="probe-1", now_monotonic=20).session
    status = subject.continue_session(dispatched, "status").session
    assert status.network_probe_results == dispatched.network_probe_results
    cancelled = subject.cancel_session(dispatched).session
    assert cancelled.network_probe_requests == dispatched.network_probe_requests
    restarted = subject.restart_session(dispatched, "reiniciar").session
    assert restarted.network_probe_requests == ()
    assert restarted.network_probe_results == ()
    assert restarted.network_probe_dispatch_results == ()


def test_session_snapshots_are_frozen_and_defensive():
    item = request_snapshot()
    source = session(network_probe_requests=(item,), current_network_probe_request=item)
    with pytest.raises(FrozenInstanceError):
        source.current_network_probe_request = None
    assert source.network_probe_requests is not (item,)
    assert source.current_network_probe_request == item


@pytest.mark.parametrize("key", ["hostname", "username", "environment", "interfaces", "mac", "routes", "dns", "gateway"])
def test_probe_flow_does_not_add_private_environment_metadata(key):
    subject, source = built()
    final = subject.dispatch_network_probe(source, probe_id="probe-1", now_monotonic=20).session
    assert key not in final.metadata


def test_network_probe_errors_are_deduplicated():
    first = build(host="bad host").session
    second = build(source=first, host="bad host").session
    errors = second.metadata["network_probe_errors"]
    assert len(errors) == len(set(errors))


@pytest.mark.parametrize("forbidden", ["socket", "subprocess", "requests", "httpx", "urllib"])
def test_session_engine_has_no_forbidden_network_imports(forbidden):
    tree = ast.parse(ENGINE_FILE.read_text(encoding="utf-8"))
    imports = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert all(name != forbidden and not name.startswith(forbidden + ".") for name in imports)


@pytest.mark.parametrize("forbidden", [
    "ping.exe", "test-netconnection", "socket.socket", "subprocess.run",
    "getaddrinfo", "gethostbyname", "send(", "connect(",
])
def test_session_engine_has_no_network_execution_primitives(forbidden):
    assert forbidden not in ENGINE_FILE.read_text(encoding="utf-8").casefold()


@pytest.mark.parametrize("path", [ENGINE_FILE, MODELS_FILE, HERE])
def test_modified_files_are_utf8_without_bom(path):
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    data.decode("utf-8")


@pytest.mark.parametrize("probe_id,request_id,timeout,dry_run", [
    (f"probe-{index}", f"request-{index}", timeout, dry_run)
    for index in range(1, 17)
    for timeout in (1000, 3000)
    for dry_run in (True, False)
])
def test_explicit_request_variants_preserve_caller_values(probe_id, request_id, timeout, dry_run):
    configured = probe_policy(allow_real_probe=True)
    turn = build(
        engine(configured), probe_id=probe_id, request_id=request_id,
        timeout_ms=timeout, dry_run=dry_run,
    )
    item = turn.session.current_network_probe_request
    assert (item.probe_id, item.request_id, item.timeout_ms, item.dry_run) == (
        probe_id, request_id, timeout, dry_run,
    )
