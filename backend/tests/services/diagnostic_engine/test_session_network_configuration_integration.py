import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    LocalAdapterDispatcher, LocalAdapterDispatchResult, LocalOperationArgument,
    SafeLocalOperationValidator,
)
from app.services.diagnostic_engine.approval_models import (
    ApprovalActor, ApprovalType, ApprovedActionGrant,
)
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction, ExecutionParameter, ExecutionPlan, ExecutionResult, ExecutionRisk,
    ExecutionStatus, ExecutionTarget,
)
from app.services.diagnostic_engine.executor_models import ExecutionContext, ExecutorRequest
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalExecutionState, LocalRawExecutionResult, LocalSanitizedResult,
)
from app.services.diagnostic_engine.local_executor_policy import DiagnosticLocalExecutorPolicy
from app.services.diagnostic_engine.session_engine import DiagnosticSessionEngine
from app.services.diagnostic_engine.session_models import DiagnosticSession, DiagnosticSessionStatus


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
SESSION_ENGINE = ROOT / "app/services/diagnostic_engine/session_engine.py"
SESSION_MODELS = SESSION_ENGINE.with_name("session_models.py")
OPERATION = "check_network_configuration"
SUPPORTED = (
    "read_system_information", "check_disk_information", "check_disk_space",
    "collect_event_logs", "list_windows_services", "check_service_status",
    "list_processes", "read_system_process_information", OPERATION,
)
UNSUPPORTED = ("ping_host", "check_port", "validate_configuration")


def network_policy(**changes):
    return replace(DiagnosticLocalExecutorPolicy(), **changes)


def graph(*, dry_run=True, arguments=()):
    parameters = tuple(
        ExecutionParameter(item.name, item.value, item.required, "Network argument")
        for item in arguments
    )
    action = ExecutionAction(
        action_id="action-1", action_name=OPERATION, title="Network configuration",
        description="Read-only local network configuration.", target=ExecutionTarget.NETWORK,
        status=ExecutionStatus.READY, risk=ExecutionRisk.LOW, parameters=parameters,
        timeout_seconds=30, requires_confirmation=False, requires_human=False,
        metadata={"action_kind": "read_only"},
    )
    grant = ApprovedActionGrant(
        grant_id="grant-1", approval_id="approval-1", execution_plan_id="plan-1",
        action_id=action.action_id, action_snapshot=action,
        approved_by=ApprovalActor("actor-1", ApprovalType.HUMAN_TECHNICIAN),
        approved_at_monotonic=1, expires_at_monotonic=100,
        metadata={"session_id": "session-1"},
    )
    context = ExecutionContext(
        session_id="session-1", diagnostic_plan_id="diagnostic-1",
        execution_plan_id="plan-1", action_id=action.action_id,
        grant_id=grant.grant_id, approval_id=grant.approval_id,
        target=action.target, risk=action.risk, requested_at_monotonic=2,
    )
    request = ExecutorRequest(
        request_id="executor-1", context=context, action_snapshot=action,
        grant_snapshot=grant, timeout_seconds=30, dry_run=dry_run,
    )
    plan = ExecutionPlan("plan-1", ExecutionStatus.READY, (action,), action.action_id)
    return DiagnosticSession(
        session_id="session-1", status=DiagnosticSessionStatus.READY_FOR_ACTION,
        original_message="Network diagnostic", last_message="Network diagnostic",
        execution_plan=plan, execution_result=ExecutionResult(True, plan, action),
        approval_grants=(grant,), executor_requests=(request,),
    )


def engine_with_network(dispatcher=None, **policy_changes):
    policy = network_policy(**policy_changes)
    return DiagnosticSessionEngine(
        local_operation_validator=SafeLocalOperationValidator(policy=policy),
        local_adapter_dispatcher=dispatcher or LocalAdapterDispatcher(policy=policy),
    )


def build(*, dry_run=True, engine=None, command_id="command-1", contract_id="contract-1",
          arguments=(), timeout_seconds=None):
    engine = engine or engine_with_network(
        allow_local_execution=not dry_run, allow_real_execution=not dry_run
    )
    source = graph(dry_run=dry_run, arguments=arguments)
    turn = engine.build_local_execution_contract(
        source, request_id="executor-1", operation_name=OPERATION,
        command_id=command_id, contract_id=contract_id, now_monotonic=10,
        arguments=arguments, dry_run=dry_run, timeout_seconds=timeout_seconds,
    )
    return engine, source, turn


def raw(state=LocalExecutionState.SUCCESS, command_id="command-1", message="network-output"):
    return LocalRawExecutionResult(
        command_id=command_id, state=state, started_at_monotonic=10,
        finished_at_monotonic=10, exit_code=0 if state == LocalExecutionState.SUCCESS else None,
        stdout=message if state == LocalExecutionState.SUCCESS else "",
        stderr="" if state == LocalExecutionState.SUCCESS else message,
        output_chunks=(), timed_out=False, cancelled=False,
        errors=() if state == LocalExecutionState.SUCCESS else (message,),
    )


def sanitized(result):
    return LocalSanitizedResult(
        command_id=result.command_id, state=result.state, exit_code=result.exit_code,
        stdout_summary=result.stdout, stderr_summary=result.stderr, redactions=(),
        truncated=False,
        output_bytes=len(result.stdout.encode()) + len(result.stderr.encode()),
        errors=result.errors,
    )


class RecordingDispatcher(LocalAdapterDispatcher):
    def __init__(self, *, result=None, raises=False, supported=(OPERATION,)):
        super().__init__()
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "configured_result", result)
        object.__setattr__(self, "raises", raises)
        object.__setattr__(self, "configured_supported", supported)

    def contains(self, operation_name):
        return operation_name in self.configured_supported

    def dispatch(self, contract, now_monotonic):
        self.calls.append((contract, now_monotonic))
        if self.raises:
            raise RuntimeError(r"sensitive C:\Users\Private network stack")
        if self.configured_result is not None:
            return self.configured_result
        result = raw(command_id=contract.command.command_id)
        return LocalAdapterDispatchResult(
            success=True, contract=contract, raw_result=result,
            sanitized_result=sanitized(result), adapter_name="FakeNetworkDispatcher",
        )


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("command_id,contract_id", [
    ("command-1", "contract-1"), ("command-2", "contract-2"),
    ("command-3", "contract-3"), ("command-4", "contract-4"),
    ("command-5", "contract-5"), ("network-command", "network-contract"),
])
def test_builds_network_contract_without_arguments(dry_run, command_id, contract_id):
    _, source, turn = build(
        dry_run=dry_run, command_id=command_id, contract_id=contract_id
    )
    contract = turn.session.current_local_execution_contract
    assert contract is not None and contract.operation.operation_name == OPERATION
    assert contract.command.operation_name == OPERATION
    assert contract.command.adapter_type == LocalAdapterType.NETWORK_DIAGNOSTIC
    assert contract.command.target == ExecutionTarget.NETWORK
    assert contract.command.arguments == () and contract.command.dry_run is dry_run
    assert turn.session.local_execution_contracts == (contract,)
    assert source.local_execution_contracts == ()


@pytest.mark.parametrize("argument", [
    LocalOperationArgument("interface", "Ethernet"),
    LocalOperationArgument("host", "localhost"),
    LocalOperationArgument("port", 80),
    LocalOperationArgument("name_filter", "Wi-Fi"),
])
def test_extra_arguments_are_blocked_by_validator_without_dispatch(argument):
    dispatcher = RecordingDispatcher(); engine = engine_with_network(dispatcher)
    _, _, turn = build(engine=engine, arguments=(argument,))
    assert turn.session.local_execution_contracts == () and dispatcher.calls == []
    assert "local_execution_errors" in turn.session.metadata


@pytest.mark.parametrize("field", [
    "allow_network_diagnostic_adapter", "allow_network_target", "allow_low_risk",
    "allow_read_only_operations", "allow_dry_run",
])
def test_policy_block_has_no_session_bypass(field):
    policy = replace(DiagnosticLocalExecutorPolicy(), **{field: False})
    engine = DiagnosticSessionEngine(
        local_operation_validator=SafeLocalOperationValidator(policy=policy),
        local_adapter_dispatcher=LocalAdapterDispatcher(policy=policy),
    )
    _, _, turn = build(engine=engine)
    assert turn.session.local_execution_contracts == ()
    assert "local_execution_errors" in turn.session.metadata


@pytest.mark.parametrize("operation", UNSUPPORTED)
def test_session_blocks_unregistered_network_operations(operation):
    dispatcher = RecordingDispatcher(); engine = engine_with_network(dispatcher)
    source = graph()
    turn = engine.build_local_execution_contract(
        source, request_id="executor-1", operation_name=operation,
        command_id="command-1", contract_id="contract-1", now_monotonic=10,
    )
    assert turn.session.local_execution_contracts == () and dispatcher.calls == []


@pytest.mark.parametrize("now", [11, 12, 13, 14, 15, 16, 20, 50, 75, 99])
def test_dry_run_routes_only_through_injected_dispatcher(now):
    dispatcher = RecordingDispatcher(); engine = engine_with_network(dispatcher)
    engine, source, built = build(engine=engine)
    before_grants = deepcopy(source.approval_grants)
    before_actions = deepcopy(source.execution_plan.actions)
    turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=now)
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0] == (built.session.current_local_execution_contract, now)
    assert turn.session.current_local_raw_result.stdout == "network-output"
    assert turn.session.current_local_sanitized_result.stdout_summary == "network-output"
    assert turn.session.approval_grants == before_grants
    assert turn.session.execution_plan.actions == before_actions
    assert turn.session.status == source.status


@pytest.mark.parametrize("identity", [
    "session", "request", "action", "grant", "plan", "approvals",
])
def test_build_preserves_input_graph(identity):
    source = graph()
    selected = {
        "session": source, "request": source.executor_requests[0],
        "action": source.execution_plan.actions[0], "grant": source.approval_grants[0],
        "plan": source.execution_plan, "approvals": source.approval_grants,
    }[identity]
    before = deepcopy(selected)
    engine_with_network().build_local_execution_contract(
        source, request_id="executor-1", operation_name=OPERATION,
        command_id="command-1", contract_id="contract-1", now_monotonic=10,
    )
    assert selected == before


def test_exact_duplicate_is_not_added():
    engine, _, first = build()
    second = engine.build_local_execution_contract(
        first.session, request_id="executor-1", operation_name=OPERATION,
        command_id="command-1", contract_id="contract-2", now_monotonic=11,
    )
    assert len(second.session.local_execution_contracts) == 1


@pytest.mark.parametrize("dry_run,timeout", [(True, 20), (True, 25), (False, 30), (False, 20)])
def test_deduplication_distinguishes_timeout_or_dry_run(dry_run, timeout):
    engine = engine_with_network(allow_local_execution=True, allow_real_execution=True)
    engine, _, first = build(engine=engine)
    second = engine.build_local_execution_contract(
        first.session, request_id="executor-1", operation_name=OPERATION,
        command_id="command-1", contract_id="contract-2", now_monotonic=11,
        dry_run=dry_run, timeout_seconds=timeout,
    )
    assert len(second.session.local_execution_contracts) == 2


@pytest.mark.parametrize("kind", ["none", "raw", "both", "exception"])
def test_dispatch_failures_preserve_only_returned_snapshots(kind):
    _, _, seed = build(); contract = seed.session.current_local_execution_contract
    raw_result = raw(LocalExecutionState.FAILED, message="controlled network failure")
    clean = sanitized(raw_result)
    result = LocalAdapterDispatchResult(
        success=False, contract=contract,
        raw_result=raw_result if kind in {"raw", "both"} else None,
        sanitized_result=clean if kind == "both" else None,
        errors=("dispatcher blocked", "dispatcher blocked"),
    )
    dispatcher = RecordingDispatcher(result=result, raises=kind == "exception")
    engine = engine_with_network(dispatcher); _, _, built = build(engine=engine)
    turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    assert len(turn.session.local_raw_results) == int(kind in {"raw", "both"})
    assert len(turn.session.local_sanitized_results) == int(kind == "both")
    if kind == "exception":
        assert turn.errors == ("Falha na execução local.",)
        assert "sensitive" not in " ".join(turn.errors).lower()


def test_real_execution_missing_backend_is_preserved(monkeypatch):
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_network_diagnostic_adapter._network_backend", None
    )
    engine = engine_with_network(allow_local_execution=True, allow_real_execution=True)
    engine, source, built = build(dry_run=False, engine=engine)
    turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    message = "Backend seguro de configuração de rede indisponível."
    assert turn.session.current_local_raw_result.stderr == message
    assert turn.session.current_local_sanitized_result.stderr_summary == message
    assert turn.session.status == source.status and not source.approval_grants[0].used


def test_default_real_execution_is_blocked_without_snapshots():
    engine = engine_with_network(); engine, _, built = build(dry_run=False, engine=engine)
    turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    assert turn.session.local_raw_results == () and turn.session.local_sanitized_results == ()
    assert "local_execution_errors" in turn.session.metadata


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
def test_history_appends_without_erasing_previous_results(count):
    dispatcher = RecordingDispatcher(); engine = engine_with_network(dispatcher)
    engine, _, built = build(engine=engine); session = built.session
    for index in range(count):
        previous = raw(command_id=f"previous-{index}")
        session = replace(
            session, local_raw_results=(*session.local_raw_results, previous),
            local_sanitized_results=(*session.local_sanitized_results, sanitized(previous)),
        )
    turn = engine.execute_local_contract(session, contract_id="contract-1", now_monotonic=11)
    assert len(turn.session.local_raw_results) == count + 1
    assert len(turn.session.local_sanitized_results) == count + 1


@pytest.mark.parametrize("field", [
    "contract_id", "executor_request_id", "execution_plan_id", "action_id", "grant_id",
    "command_id", "operation_name", "adapter_type", "target", "risk", "dry_run", "arguments",
])
def test_contract_preserves_network_structural_fields(field):
    _, _, turn = build(); contract = turn.session.current_local_execution_contract
    observed = {
        "contract_id": contract.contract_id, "executor_request_id": contract.executor_request_id,
        "execution_plan_id": contract.execution_plan_id, "action_id": contract.action_id,
        "grant_id": contract.grant_id, "command_id": contract.command.command_id,
        "operation_name": contract.command.operation_name,
        "adapter_type": contract.command.adapter_type, "target": contract.command.target,
        "risk": contract.command.risk, "dry_run": contract.command.dry_run,
        "arguments": contract.command.arguments,
    }[field]
    expected = {
        "contract_id": "contract-1", "executor_request_id": "executor-1",
        "execution_plan_id": "plan-1", "action_id": "action-1", "grant_id": "grant-1",
        "command_id": "command-1", "operation_name": OPERATION,
        "adapter_type": LocalAdapterType.NETWORK_DIAGNOSTIC,
        "target": ExecutionTarget.NETWORK, "risk": ExecutionRisk.LOW,
        "dry_run": True, "arguments": (),
    }[field]
    assert observed == expected


@pytest.mark.parametrize("forbidden", [
    "mac", "hostname", "username", "sid", "domain", "ssid", "bssid",
    "password", "dns", "gateway", "routes", "arp", "connections", "ports",
    "remote_endpoints",
])
def test_session_does_not_enrich_dispatcher_output(forbidden):
    dispatcher = RecordingDispatcher(); engine = engine_with_network(dispatcher)
    engine, _, built = build(engine=engine)
    turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    stored = turn.session.current_local_sanitized_result.stdout_summary
    assert stored == "network-output" and forbidden not in stored.lower()


@pytest.mark.parametrize("operation", SUPPORTED)
def test_dispatcher_support_set_remains_intact(operation):
    dispatcher = LocalAdapterDispatcher(); before = dispatcher.supported_operations()
    assert dispatcher.contains(operation) and dispatcher.supported_operations() == before


@pytest.mark.parametrize("forbidden", [
    "localnetworkdiagnosticadapter", "psutil", "net_if_addrs", "net_if_stats",
    "socket", ".connect(", ".send(", ".sendto(", "dns_lookup", "requests.",
    "httpx.", "urllib.", "subprocess", "os.system", "powershell", "cmd.exe",
    "ipconfig", "netsh", "wmic", "ping_host", "check_port", "traceroute",
])
def test_session_engine_has_no_network_adapter_probe_or_fallback(forbidden):
    assert forbidden not in SESSION_ENGINE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("module", ["psutil", "socket", "requests", "httpx", "urllib", "subprocess"])
def test_session_engine_has_no_forbidden_operational_import(module):
    tree = ast.parse(SESSION_ENGINE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert module not in imports


@pytest.mark.parametrize("path", [SESSION_ENGINE, SESSION_MODELS, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes()
    assert not content.startswith(b"\xef\xbb\xbf")
    content.decode("utf-8")
