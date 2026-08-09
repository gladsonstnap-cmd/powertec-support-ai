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
SERVICE_OPERATIONS = ("list_windows_services", "check_service_status")
SUPPORTED = (
    "read_system_information", "check_disk_information", "check_disk_space",
    "collect_event_logs", "list_windows_services", "check_service_status",
)
UNSUPPORTED = (
    "list_processes", "read_system_process_information", "check_network_configuration",
    "ping_host", "check_port", "validate_configuration", "unknown_operation",
    "start_service", "stop_service", "restart_service", "pause_service",
    "resume_service", "change_startup_type",
)


def service_policy(**changes):
    return replace(
        DiagnosticLocalExecutorPolicy(), allow_windows_service_adapter=True, **changes
    )


def graph(operation="list_windows_services", *, arguments=(), dry_run=True):
    parameters = tuple(
        ExecutionParameter(item.name, item.value, item.required, "Service query argument")
        for item in arguments
    )
    action = ExecutionAction(
        action_id="action-1", action_name=operation, title="Windows service query",
        description="Read-only Windows service operation.", target=ExecutionTarget.WINDOWS,
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
    session = DiagnosticSession(
        session_id="session-1", status=DiagnosticSessionStatus.READY_FOR_ACTION,
        original_message="Service diagnostic", last_message="Service diagnostic",
        execution_plan=plan, execution_result=ExecutionResult(True, plan, action),
        approval_grants=(grant,), executor_requests=(request,),
    )
    return session


def arguments_for(operation, value=None):
    if operation == "check_service_status":
        return () if value is None else (LocalOperationArgument("service_name", value, required=True),)
    return () if value is None else (LocalOperationArgument("name_filter", value),)


def engine_with_services(dispatcher=None, **policy_changes):
    policy = service_policy(**policy_changes)
    return DiagnosticSessionEngine(
        local_operation_validator=SafeLocalOperationValidator(policy=policy),
        local_adapter_dispatcher=dispatcher or LocalAdapterDispatcher(policy=policy),
    )


def build(operation="list_windows_services", *, value=None, dry_run=True, engine=None,
          command_id="command-1", contract_id="contract-1"):
    engine = engine or engine_with_services(
        allow_local_execution=not dry_run, allow_real_execution=not dry_run
    )
    arguments = arguments_for(operation, value)
    source = graph(operation, arguments=arguments, dry_run=dry_run)
    turn = engine.build_local_execution_contract(
        source, request_id="executor-1", operation_name=operation,
        command_id=command_id, contract_id=contract_id, now_monotonic=10,
        arguments=arguments, dry_run=dry_run,
    )
    return engine, source, turn


def raw(state=LocalExecutionState.SUCCESS, command_id="command-1", message="service-output"):
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
    def __init__(self, *, result=None, raises=False, supported=SERVICE_OPERATIONS):
        super().__init__(policy=service_policy())
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "configured_result", result)
        object.__setattr__(self, "raises", raises)
        object.__setattr__(self, "configured_supported", supported)

    def contains(self, operation_name):
        return operation_name in self.configured_supported

    def dispatch(self, contract, now_monotonic):
        self.calls.append((contract, now_monotonic))
        if self.raises:
            raise RuntimeError(r"sensitive C:\Users\Private service stack")
        if self.configured_result is not None:
            return self.configured_result
        result = raw(command_id=contract.command.command_id)
        return LocalAdapterDispatchResult(
            success=True, contract=contract, raw_result=result,
            sanitized_result=sanitized(result), adapter_name="FakeServiceDispatcher",
        )


@pytest.mark.parametrize("operation,value", [
    ("list_windows_services", None), ("list_windows_services", "Print"),
    ("list_windows_services", "Windows Update"),
    ("check_service_status", "Spooler"), ("check_service_status", "wuauserv"),
    ("check_service_status", "BITS"),
])
@pytest.mark.parametrize("dry_run", [True, False])
def test_builds_structured_service_contracts(operation, value, dry_run):
    _, source, turn = build(operation, value=value, dry_run=dry_run)
    contract = turn.session.current_local_execution_contract
    assert contract is not None and contract.command.operation_name == operation
    assert contract.command.adapter_type == LocalAdapterType.WINDOWS_SERVICE
    assert contract.command.arguments == arguments_for(operation, value)
    assert contract.command.dry_run is dry_run
    assert turn.session.local_execution_contracts == (contract,)
    assert source.local_execution_contracts == ()


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
def test_default_policy_blocks_service_contract_without_bypass(operation):
    source = graph(operation, arguments=arguments_for(operation, "Spooler"))
    turn = DiagnosticSessionEngine().build_local_execution_contract(
        source, request_id="executor-1", operation_name=operation,
        command_id="command-1", contract_id="contract-1", now_monotonic=10,
        arguments=arguments_for(operation, "Spooler"),
    )
    assert turn.session.local_execution_contracts == ()
    assert "local_execution_errors" in turn.session.metadata


@pytest.mark.parametrize("operation", UNSUPPORTED)
def test_session_blocks_operations_not_supported_by_dispatcher(operation):
    dispatcher = RecordingDispatcher(); engine = engine_with_services(dispatcher)
    source = graph("list_windows_services")
    turn = engine.build_local_execution_contract(
        source, request_id="executor-1", operation_name=operation,
        command_id="command-1", contract_id="contract-1", now_monotonic=10,
    )
    assert turn.session.local_execution_contracts == () and dispatcher.calls == []


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
@pytest.mark.parametrize("value", ["Spooler", "BITS", "Windows Update"])
def test_dry_run_routes_only_through_injected_dispatcher(operation, value):
    dispatcher = RecordingDispatcher(); engine = engine_with_services(dispatcher)
    engine, source, built = build(operation, value=value, engine=engine)
    before_grant = deepcopy(source.approval_grants)
    before_action = deepcopy(source.execution_plan.actions)
    turn = engine.execute_local_contract(
        built.session, contract_id="contract-1", now_monotonic=11,
    )
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0][0] == built.session.current_local_execution_contract
    assert turn.session.current_local_raw_result.stdout == "service-output"
    assert turn.session.current_local_sanitized_result.stdout_summary == "service-output"
    assert turn.session.approval_grants == before_grant
    assert turn.session.execution_plan.actions == before_action
    assert turn.session.status == source.status


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
def test_service_argument_is_preserved_without_session_normalization(operation):
    value = "My Service_1.test"
    _, _, turn = build(operation, value=value)
    assert turn.session.current_local_execution_contract.command.arguments == arguments_for(operation, value)


@pytest.mark.parametrize("value", [None, "", "   ", "*", "../svc", "svc|whoami"])
def test_missing_or_invalid_service_name_is_controlled(value):
    _, _, turn = build("check_service_status", value=value)
    if value is None:
        assert turn.session.local_execution_contracts == ()
    else:
        assert "local_execution_errors" in turn.session.metadata or turn.session.local_execution_contracts


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
@pytest.mark.parametrize("identity", ["request", "action", "grant", "plan", "session"])
def test_build_does_not_mutate_input_graph(operation, identity):
    args = arguments_for(operation, "Spooler")
    source = graph(operation, arguments=args)
    selected = {
        "request": source.executor_requests[0], "action": source.execution_plan.actions[0],
        "grant": source.approval_grants[0], "plan": source.execution_plan,
        "session": source,
    }[identity]
    before = deepcopy(selected)
    engine_with_services().build_local_execution_contract(
        source, request_id="executor-1", operation_name=operation,
        command_id="command-1", contract_id="contract-1", now_monotonic=10,
        arguments=args,
    )
    assert selected == before


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
@pytest.mark.parametrize("value", ["Alpha", "Beta", "Gamma"])
def test_deduplication_distinguishes_service_arguments(operation, value):
    _, _, first = build(operation, value=value)
    _, _, second = build(
        operation, value=value + "2", command_id="command-2", contract_id="contract-2"
    )
    first_contract = first.session.current_local_execution_contract
    second_contract = second.session.current_local_execution_contract
    assert first_contract.command.arguments != second_contract.command.arguments
    assert first_contract != second_contract


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
def test_exact_duplicate_is_not_added(operation):
    engine, _, first = build(operation, value="Spooler")
    second = engine.build_local_execution_contract(
        first.session, request_id="executor-1", operation_name=operation,
        command_id="command-1", contract_id="contract-2", now_monotonic=11,
        arguments=arguments_for(operation, "Spooler"),
    )
    assert len(second.session.local_execution_contracts) == 1


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
@pytest.mark.parametrize("result_kind", ["none", "raw", "both", "exception"])
def test_dispatch_failures_preserve_only_returned_snapshots(operation, result_kind):
    _, _, seed = build(operation, value="Spooler")
    contract = seed.session.current_local_execution_contract
    raw_result = raw(LocalExecutionState.FAILED, message="controlled service failure")
    clean = sanitized(raw_result)
    result = LocalAdapterDispatchResult(
        success=False, contract=contract,
        raw_result=raw_result if result_kind in {"raw", "both"} else None,
        sanitized_result=clean if result_kind == "both" else None,
        errors=("dispatcher blocked", "dispatcher blocked"),
    )
    dispatcher = RecordingDispatcher(result=result, raises=result_kind == "exception")
    engine = engine_with_services(dispatcher)
    _, _, built = build(operation, value="Spooler", engine=engine)
    turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    assert len(turn.session.local_raw_results) == int(result_kind in {"raw", "both"})
    assert len(turn.session.local_sanitized_results) == int(result_kind == "both")
    if result_kind == "exception":
        assert turn.errors == ("Falha na execução local.",)
        assert "sensitive" not in " ".join(turn.errors).lower()


def test_real_execution_missing_backend_is_preserved(monkeypatch):
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_windows_service_adapter._service_backend", None
    )
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_windows_service_adapter.platform.system",
        lambda: "Windows",
    )
    engine = engine_with_services(allow_local_execution=True, allow_real_execution=True)
    engine, source, built = build("list_windows_services", dry_run=False, engine=engine)
    turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    message = "Backend seguro de serviços do Windows indisponível."
    assert turn.session.current_local_raw_result.stderr == message
    assert turn.session.current_local_sanitized_result.stderr_summary == message
    assert turn.session.status == source.status and not source.approval_grants[0].used


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
def test_default_real_execution_is_blocked_without_fake_snapshots(operation):
    engine = engine_with_services()
    engine, _, built = build(operation, value="Spooler", dry_run=False, engine=engine)
    turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    assert turn.session.local_raw_results == () and turn.session.local_sanitized_results == ()
    assert "local_execution_errors" in turn.session.metadata


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
@pytest.mark.parametrize("field", [
    "contract_id", "executor_request_id", "execution_plan_id", "action_id", "grant_id",
    "command_id", "operation_name", "adapter_type", "target", "risk", "dry_run", "arguments",
])
def test_built_contract_preserves_structural_service_fields(operation, field):
    value = "Spooler"
    _, _, turn = build(operation, value=value)
    contract = turn.session.current_local_execution_contract
    observed = {
        "contract_id": contract.contract_id,
        "executor_request_id": contract.executor_request_id,
        "execution_plan_id": contract.execution_plan_id,
        "action_id": contract.action_id,
        "grant_id": contract.grant_id,
        "command_id": contract.command.command_id,
        "operation_name": contract.command.operation_name,
        "adapter_type": contract.command.adapter_type,
        "target": contract.command.target,
        "risk": contract.command.risk,
        "dry_run": contract.command.dry_run,
        "arguments": contract.command.arguments,
    }[field]
    expected = {
        "contract_id": "contract-1", "executor_request_id": "executor-1",
        "execution_plan_id": "plan-1", "action_id": "action-1", "grant_id": "grant-1",
        "command_id": "command-1", "operation_name": operation,
        "adapter_type": LocalAdapterType.WINDOWS_SERVICE, "target": ExecutionTarget.WINDOWS,
        "risk": ExecutionRisk.LOW, "dry_run": True,
        "arguments": arguments_for(operation, value),
    }[field]
    assert observed == expected


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_local_history_appends_without_erasing_previous_results(operation, count):
    dispatcher = RecordingDispatcher(); engine = engine_with_services(dispatcher)
    engine, _, built = build(operation, value="Spooler", engine=engine)
    session = built.session
    for index in range(count):
        result = raw(command_id=f"previous-{index}")
        session = replace(
            session, local_raw_results=(*session.local_raw_results, result),
            local_sanitized_results=(*session.local_sanitized_results, sanitized(result)),
        )
    turn = engine.execute_local_contract(session, contract_id="contract-1", now_monotonic=11)
    assert len(turn.session.local_raw_results) == count + 1
    assert len(turn.session.local_sanitized_results) == count + 1


@pytest.mark.parametrize("operation", SUPPORTED)
def test_dispatcher_support_set_remains_intact(operation):
    dispatcher = LocalAdapterDispatcher()
    before = dispatcher.supported_operations()
    assert dispatcher.contains(operation)
    assert dispatcher.supported_operations() == before


@pytest.mark.parametrize("forbidden", [
    "win32service", "win32serviceutil", "openscmanager", "openservice(",
    "enumservicesstatus", "queryservicestatus", "startservice(", "controlservice(",
    "changeserviceconfig(", "createservice(", "deleteservice(", "subprocess",
    "os.system", "powershell.exe", "cmd.exe", "sc.exe", "net.exe", "wmic",
    "socket.socket", "requests.get", "httpx.get", "start_service", "stop_service",
    "restart_service", "pause_service", "resume_service", "change_startup_type",
])
def test_session_engine_has_no_service_api_mutation_or_fallback(forbidden):
    assert forbidden not in SESSION_ENGINE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("module", ["win32service", "win32serviceutil", "subprocess", "socket"])
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
