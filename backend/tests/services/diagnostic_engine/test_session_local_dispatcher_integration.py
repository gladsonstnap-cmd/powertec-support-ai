import ast
from collections import namedtuple
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    LocalAdapterDispatcher, LocalAdapterDispatchResult, LocalDiskInformationAdapter,
    LocalOperationArgument, LocalSystemInformationAdapter, SafeLocalOperationValidator,
)
from app.services.diagnostic_engine.approval_models import ApprovalActor, ApprovalType, ApprovedActionGrant
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction, ExecutionParameter, ExecutionPlan, ExecutionResult, ExecutionRisk,
    ExecutionStatus, ExecutionTarget,
)
from app.services.diagnostic_engine.executor_models import ExecutionContext, ExecutorRequest
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalExecutionState, LocalOperationType, LocalRawExecutionResult,
    LocalSanitizedResult,
)
from app.services.diagnostic_engine.local_executor_policy import DiagnosticLocalExecutorPolicy
from app.services.diagnostic_engine.session_engine import DiagnosticSessionEngine
from app.services.diagnostic_engine.session_models import DiagnosticSession, DiagnosticSessionStatus


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
SESSION_ENGINE = ROOT / "app/services/diagnostic_engine/session_engine.py"
SESSION_MODELS = SESSION_ENGINE.with_name("session_models.py")
DiskUsage = namedtuple("DiskUsage", "total used free")
SUPPORTED = ("read_system_information", "check_disk_information", "check_disk_space")
UNSUPPORTED = (
    "list_windows_services", "check_service_status", "collect_event_logs", "list_processes",
    "read_system_process_information", "check_network_configuration", "ping_host", "check_port",
    "validate_configuration", "unknown_operation",
)


def graph(operation="read_system_information", *, argument=None, dry_run=True):
    argument_name = {
        "check_disk_information": "disk_name", "check_disk_space": "drive",
    }.get(operation)
    parameters = (
        () if argument is None else
        (ExecutionParameter(argument_name, argument, False, "Structured disk identifier"),)
    )
    item = ExecutionAction(
        action_id="action-1", action_name=operation, title="Local read",
        description="Read-only local operation.", target=ExecutionTarget.WINDOWS,
        status=ExecutionStatus.READY, risk=ExecutionRisk.LOW, parameters=parameters,
        timeout_seconds=30, requires_confirmation=False, requires_human=False,
        metadata={"action_kind": "read_only"},
    )
    grant = ApprovedActionGrant(
        grant_id="grant-1", approval_id="approval-1", execution_plan_id="plan-1",
        action_id=item.action_id, action_snapshot=item,
        approved_by=ApprovalActor("actor-1", ApprovalType.HUMAN_TECHNICIAN),
        approved_at_monotonic=1, expires_at_monotonic=100,
        metadata={"session_id": "session-1"},
    )
    context = ExecutionContext(
        session_id="session-1", diagnostic_plan_id="diagnostic-1", execution_plan_id="plan-1",
        action_id=item.action_id, grant_id=grant.grant_id, approval_id=grant.approval_id,
        target=item.target, risk=item.risk, requested_at_monotonic=2,
    )
    request = ExecutorRequest(
        request_id="executor-1", context=context, action_snapshot=item,
        grant_snapshot=grant, timeout_seconds=30, dry_run=dry_run,
    )
    plan = ExecutionPlan("plan-1", ExecutionStatus.READY, (item,), item.action_id)
    source = DiagnosticSession(
        session_id="session-1", status=DiagnosticSessionStatus.READY_FOR_ACTION,
        original_message="Erro", last_message="Erro", execution_plan=plan,
        execution_result=ExecutionResult(True, plan, item), approval_grants=(grant,),
        executor_requests=(request,),
    )
    arguments = () if argument is None else (LocalOperationArgument(argument_name, argument),)
    return source, arguments


def build(engine, operation="read_system_information", *, argument=None, dry_run=True):
    source, arguments = graph(operation, argument=argument, dry_run=dry_run)
    turn = engine.build_local_execution_contract(
        source, request_id="executor-1", operation_name=operation, command_id="command-1",
        contract_id="contract-1", now_monotonic=10, arguments=arguments, dry_run=dry_run,
    )
    return source, turn


def execute(engine, operation="read_system_information", *, argument=None, dry_run=True):
    source, built = build(engine, operation, argument=argument, dry_run=dry_run)
    turn = engine.execute_local_contract(
        built.session, contract_id="contract-1", now_monotonic=11,
    )
    return source, built.session, turn


class RecordingDispatcher(LocalAdapterDispatcher):
    def __init__(self, *, result=None, raises=False, supported=SUPPORTED):
        super().__init__()
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "raises", raises)
        object.__setattr__(self, "supported", tuple(supported))

    def contains(self, operation_name):
        return operation_name in self.supported

    def dispatch(self, contract, now_monotonic):
        self.calls.append((contract, now_monotonic))
        if self.raises:
            raise RuntimeError(r"sensitive C:\\private\\stack")
        if self.result is not None:
            return self.result
        return super().dispatch(contract, now_monotonic)


def windows_system(monkeypatch):
    values = {
        "system": "Windows", "release": "11", "version": "10.0", "machine": "AMD64",
        "processor": "CPU", "python_version": "3.12", "node": "HOST-PRIVATE",
    }
    for name, value in values.items():
        monkeypatch.setattr(
            f"app.services.diagnostic_engine.local_system_information_adapter.platform.{name}",
            lambda selected=value: selected,
        )
    monkeypatch.setattr("app.services.diagnostic_engine.local_system_information_adapter.sys.platform", "win32")
    monkeypatch.setattr("app.services.diagnostic_engine.local_system_information_adapter.os.cpu_count", lambda: 8)


def windows_disk(monkeypatch):
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_disk_information_adapter.platform.system",
        lambda: "Windows",
    )
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_disk_information_adapter.shutil.disk_usage",
        lambda target: DiskUsage(100, 25, 75),
    )


def real_engine():
    policy = replace(DiagnosticLocalExecutorPolicy(), allow_local_execution=True, allow_real_execution=True)
    validator = SafeLocalOperationValidator(policy=policy)
    return DiagnosticSessionEngine(local_operation_validator=validator)


def test_constructor_has_default_dispatcher():
    assert isinstance(DiagnosticSessionEngine().local_adapter_dispatcher, LocalAdapterDispatcher)


def test_constructor_preserves_custom_dispatcher():
    dispatcher = RecordingDispatcher(); engine = DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    assert engine.local_adapter_dispatcher is dispatcher


@pytest.mark.parametrize("invalid", [None, object(), "dispatcher", 1])
def test_constructor_rejects_explicit_invalid_dispatcher(invalid):
    if invalid is None:
        assert isinstance(DiagnosticSessionEngine(local_adapter_dispatcher=invalid).local_adapter_dispatcher, LocalAdapterDispatcher)
    else:
        with pytest.raises(ValueError, match="local_adapter_dispatcher"):
            DiagnosticSessionEngine(local_adapter_dispatcher=invalid)


def test_legacy_system_adapter_is_routed_through_dispatcher():
    adapter = LocalSystemInformationAdapter(); engine = DiagnosticSessionEngine(local_system_information_adapter=adapter)
    assert engine.local_system_information_adapter is adapter
    assert engine.local_adapter_dispatcher.system_information_adapter is adapter


def test_start_session_does_not_dispatch():
    dispatcher = RecordingDispatcher(); DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher).start_session("Erro")
    assert dispatcher.calls == []


@pytest.mark.parametrize("command", ["status", "cancelar", "humano", "reiniciar"])
def test_session_commands_do_not_dispatch(command):
    dispatcher = RecordingDispatcher(); engine = DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    engine.continue_session(graph()[0], command)
    assert dispatcher.calls == []


@pytest.mark.parametrize("operation", SUPPORTED)
def test_build_supports_only_dispatcher_operations(operation):
    _, turn = build(DiagnosticSessionEngine(), operation)
    assert len(turn.session.local_execution_contracts) == 1
    assert turn.session.current_local_execution_contract.command.operation_name == operation
    assert turn.session.local_raw_results == () and turn.session.local_sanitized_results == ()


@pytest.mark.parametrize("operation", UNSUPPORTED)
def test_build_blocks_catalog_operations_without_registered_adapter(operation):
    source, _ = graph()
    turn = DiagnosticSessionEngine().build_local_execution_contract(
        source, request_id="executor-1", operation_name=operation, command_id="command-1",
        contract_id="contract-1", now_monotonic=10,
    )
    assert turn.session.local_execution_contracts == ()
    assert "local_execution_errors" in turn.session.metadata


@pytest.mark.parametrize("operation,argument", [
    ("check_disk_information", None), ("check_disk_information", "C:"),
    ("check_disk_space", None), ("check_disk_space", "D:"),
])
def test_disk_contract_accepts_structured_optional_argument(operation, argument):
    _, turn = build(DiagnosticSessionEngine(), operation, argument=argument)
    expected = () if argument is None else (argument,)
    assert tuple(item.value for item in turn.session.current_local_execution_contract.command.arguments) == expected


@pytest.mark.parametrize("operation", SUPPORTED)
def test_dry_run_dispatch_stores_raw_and_sanitized(operation):
    _, built, turn = execute(DiagnosticSessionEngine(), operation)
    assert turn.session.status == built.status
    assert len(turn.session.local_raw_results) == len(turn.session.local_sanitized_results) == 1
    assert turn.session.current_local_raw_result.state == LocalExecutionState.SUCCESS
    assert turn.session.current_local_sanitized_result.state == LocalExecutionState.SUCCESS


@pytest.mark.parametrize("operation", SUPPORTED)
def test_custom_dispatcher_is_called_once_for_each_supported_operation(operation):
    dispatcher = RecordingDispatcher(); engine = DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    _, built, turn = execute(engine, operation)
    assert len(dispatcher.calls) == 1 and dispatcher.calls[0][0] == built.current_local_execution_contract
    assert turn.session.current_local_raw_result is not None


def test_real_system_information_remains_sanitized(monkeypatch):
    windows_system(monkeypatch); engine = real_engine()
    _, _, turn = execute(engine, dry_run=False)
    assert turn.session.current_local_raw_result.state == LocalExecutionState.SUCCESS
    assert "HOST-PRIVATE" not in turn.session.current_local_sanitized_result.stdout_summary


@pytest.mark.parametrize("operation,argument,key", [
    ("check_disk_information", "C:", "device"),
    ("check_disk_space", "D:", "drive"),
])
def test_real_disk_operations_are_routed_and_sanitized(monkeypatch, operation, argument, key):
    windows_disk(monkeypatch); engine = real_engine()
    _, _, turn = execute(engine, operation, argument=argument, dry_run=False)
    assert turn.session.current_local_raw_result.state == LocalExecutionState.SUCCESS
    assert f'"{key}":"{argument}"' in turn.session.current_local_sanitized_result.stdout_summary


def test_dispatch_failure_does_not_invent_results():
    result = LocalAdapterDispatchResult(success=False, errors=("blocked", "blocked"))
    dispatcher = RecordingDispatcher(result=result); engine = DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    _, built = build(engine); turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    assert turn.session.local_raw_results == () and turn.session.local_sanitized_results == ()
    assert turn.session.metadata["local_execution_errors"] == ("blocked",)


def test_dispatch_exception_is_generic_without_data_leak():
    dispatcher = RecordingDispatcher(raises=True); engine = DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    _, built = build(engine); turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    assert turn.errors == ("Falha na execução local.",)
    assert "private" not in str(turn.session.metadata).lower()
    assert turn.session.local_raw_results == () and turn.session.local_sanitized_results == ()


@pytest.mark.parametrize("field", ["status", "approval_grants", "executor_requests", "execution_plan"])
@pytest.mark.parametrize("operation", SUPPORTED)
def test_dispatch_preserves_authorization_and_session_state(field, operation):
    engine = DiagnosticSessionEngine(); source, built, turn = execute(engine, operation)
    assert getattr(turn.session, field) == getattr(built, field)
    assert source.approval_grants[0].used is False and turn.session.approval_grants[0].used is False


@pytest.mark.parametrize("operation", SUPPORTED)
@pytest.mark.parametrize("subject", ["session", "contract", "grant", "action", "request"])
def test_previous_snapshots_are_not_mutated(operation, subject):
    engine = DiagnosticSessionEngine(); _, built_turn = build(engine, operation); built = built_turn.session
    before = deepcopy(built); contract_before = deepcopy(built.current_local_execution_contract)
    engine.execute_local_contract(built, contract_id="contract-1", now_monotonic=11)
    mapping = {
        "session": (built, before),
        "contract": (built.current_local_execution_contract, contract_before),
        "grant": (built.approval_grants[0], before.approval_grants[0]),
        "action": (built.execution_plan.actions[0], before.execution_plan.actions[0]),
        "request": (built.executor_requests[0], before.executor_requests[0]),
    }
    assert mapping[subject][0] == mapping[subject][1]


@pytest.mark.parametrize("operation", SUPPORTED)
@pytest.mark.parametrize("field,value", [
    ("command.target", ExecutionTarget.LINUX),
    ("command.risk", ExecutionRisk.HIGH),
    ("command.operation_type", LocalOperationType.STATE_CHANGING),
    ("operation.operation_type", LocalOperationType.DESTRUCTIVE),
    ("command.adapter_type", LocalAdapterType.UNKNOWN),
    ("operation.adapter_type", LocalAdapterType.PROCESS),
    ("command.timeout_seconds", 0),
    ("command.dry_run", "true"),
])
def test_dispatcher_blocks_tampered_contract_without_session_fallback(operation, field, value):
    engine = DiagnosticSessionEngine(); _, built_turn = build(engine, operation); built = built_turn.session
    tampered = deepcopy(built.current_local_execution_contract)
    parent, child = field.split("."); object.__setattr__(getattr(tampered, parent), child, value)
    prepared = replace(built, local_execution_contracts=(tampered,))
    turn = engine.execute_local_contract(prepared, contract_id="contract-1", now_monotonic=11)
    assert turn.session.local_raw_results == () and turn.session.local_sanitized_results == ()
    assert "local_execution_errors" in turn.session.metadata


@pytest.mark.parametrize("operation", SUPPORTED)
@pytest.mark.parametrize("state", [
    LocalExecutionState.BLOCKED, LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS,
    LocalExecutionState.FAILED, LocalExecutionState.CANCELLED, LocalExecutionState.TIMED_OUT,
])
def test_dispatcher_blocks_invalid_contract_state(operation, state):
    engine = DiagnosticSessionEngine(); _, built_turn = build(engine, operation); built = built_turn.session
    tampered = deepcopy(built.current_local_execution_contract); object.__setattr__(tampered, "state", state)
    prepared = replace(built, local_execution_contracts=(tampered,))
    turn = engine.execute_local_contract(prepared, contract_id="contract-1", now_monotonic=11)
    assert turn.session.local_raw_results == () and "local_execution_errors" in turn.session.metadata


def test_multiple_operations_append_history_without_overwriting():
    engine = DiagnosticSessionEngine(); _, first = build(engine)
    first_run = engine.execute_local_contract(first.session, contract_id="contract-1", now_monotonic=11).session
    disk_source, args = graph("check_disk_space", argument="C:")
    disk_source = replace(
        disk_source,
        local_execution_contracts=first_run.local_execution_contracts,
        local_raw_results=first_run.local_raw_results,
        local_sanitized_results=first_run.local_sanitized_results,
    )
    second = engine.build_local_execution_contract(
        disk_source, request_id="executor-1", operation_name="check_disk_space",
        command_id="command-2", contract_id="contract-2", now_monotonic=12, arguments=args,
    ).session
    final = engine.execute_local_contract(second, contract_id="contract-2", now_monotonic=13).session
    assert len(final.local_execution_contracts) == 2
    assert len(final.local_raw_results) == len(final.local_sanitized_results) == 2


@pytest.mark.parametrize("command", ["status", "cancelar", "humano"])
@pytest.mark.parametrize("field", ["local_execution_contracts", "local_raw_results", "local_sanitized_results"])
def test_commands_preserve_local_history(command, field):
    engine = DiagnosticSessionEngine(); _, _, executed_turn = execute(engine)
    updated = engine.continue_session(executed_turn.session, command).session
    assert getattr(updated, field) == getattr(executed_turn.session, field)


@pytest.mark.parametrize("field", [
    "local_execution_contracts", "local_raw_results", "local_sanitized_results",
    "current_local_execution_contract", "current_local_raw_result", "current_local_sanitized_result",
])
def test_restart_clears_local_history(field):
    engine = DiagnosticSessionEngine(); _, _, turn = execute(engine)
    restarted = engine.restart_session(turn.session, "reiniciar").session
    assert getattr(restarted, field) in ((), None)


@pytest.mark.parametrize("operation", SUPPORTED)
def test_dispatch_does_not_change_execution_action_status(operation):
    engine = DiagnosticSessionEngine(); _, built, turn = execute(engine, operation)
    assert turn.session.execution_plan.actions[0].status == built.execution_plan.actions[0].status
    assert turn.session.execution_plan.actions[0].status == ExecutionStatus.READY


@pytest.mark.parametrize("name", ["subprocess", "os", "socket", "requests", "httpx", "pathlib", "shutil", "platform"])
def test_session_engine_has_no_operational_imports(name):
    tree = ast.parse(SESSION_ENGINE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "os.system", "subprocess.run", "powershell.exe", "cmd.exe", "socket.socket",
    "requests.get", "httpx.get", "shutil.disk_usage", "platform.system", "consume_grant",
])
def test_local_execution_section_has_no_forbidden_calls(text):
    source = SESSION_ENGINE.read_text(encoding="utf-8")
    section = source[source.index("def build_local_execution_contract"):source.index("def _status_for")]
    assert text not in section.lower()


def test_execute_local_contract_uses_dispatch_only():
    source = SESSION_ENGINE.read_text(encoding="utf-8")
    section = source[source.index("def execute_local_contract"):source.index("def _local_execution_error")]
    assert "local_adapter_dispatcher.dispatch" in section
    assert "local_system_information_adapter.execute" not in section
    assert "local_disk_information_adapter" not in section


@pytest.mark.parametrize("path", [SESSION_ENGINE, SESSION_MODELS, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
