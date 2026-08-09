import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    LocalAdapterDispatcher, LocalAdapterDispatchResult, LocalOperationArgument,
    SafeLocalOperationValidator,
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
from app.services.diagnostic_engine.local_operation_validator import LocalOperationValidationResult
from app.services.diagnostic_engine.session_engine import DiagnosticSessionEngine
from app.services.diagnostic_engine.session_models import DiagnosticSession, DiagnosticSessionStatus


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
SESSION_ENGINE = ROOT / "app/services/diagnostic_engine/session_engine.py"
SESSION_MODELS = SESSION_ENGINE.with_name("session_models.py")
SUPPORTED = (
    "read_system_information", "check_disk_information", "check_disk_space", "collect_event_logs",
)
UNSUPPORTED = (
    "list_windows_services", "check_service_status", "list_processes",
    "read_system_process_information", "check_network_configuration", "ping_host", "check_port",
    "validate_configuration", "unknown_operation",
)


def graph(*, log_name="System", hours=None, dry_run=True, operation="collect_event_logs"):
    parameters = []
    arguments = []
    if operation == "collect_event_logs":
        if log_name is not None:
            parameters.append(ExecutionParameter("log_name", log_name, True, "Allowed Event Log"))
            arguments.append(LocalOperationArgument("log_name", log_name, required=True))
        if hours is not None:
            parameters.append(ExecutionParameter("hours", hours, False, "Bounded time window"))
            arguments.append(LocalOperationArgument("hours", hours))
    item = ExecutionAction(
        action_id="action-1", action_name=operation, title="Local read",
        description="Read-only local operation.", target=ExecutionTarget.WINDOWS,
        status=ExecutionStatus.READY, risk=ExecutionRisk.LOW, parameters=tuple(parameters),
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
    return source, tuple(arguments)


def build(engine=None, *, log_name="System", hours=None, dry_run=True, operation="collect_event_logs", **changes):
    engine = engine or DiagnosticSessionEngine()
    source, arguments = graph(log_name=log_name, hours=hours, dry_run=dry_run, operation=operation)
    values = dict(
        request_id="executor-1", operation_name=operation, command_id="command-1",
        contract_id="contract-1", now_monotonic=10, arguments=arguments, dry_run=dry_run,
    )
    values.update(changes)
    return engine, source, engine.build_local_execution_contract(source, **values)


def execute(engine=None, **changes):
    engine, source, built = build(engine, **changes)
    turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    return engine, source, built.session, turn


def raw(state=LocalExecutionState.SUCCESS):
    return LocalRawExecutionResult(
        command_id="command-1", state=state, started_at_monotonic=10,
        finished_at_monotonic=10, exit_code=0 if state == LocalExecutionState.SUCCESS else None,
        stdout='{"event_count":0,"events":[],"log_name":"System"}' if state == LocalExecutionState.SUCCESS else "",
        stderr="" if state == LocalExecutionState.SUCCESS else "controlled event failure",
        output_chunks=(), timed_out=False, cancelled=False,
        errors=() if state == LocalExecutionState.SUCCESS else ("controlled event failure",),
    )


def sanitized(source):
    return LocalSanitizedResult(
        command_id=source.command_id, state=source.state, exit_code=source.exit_code,
        stdout_summary=source.stdout, stderr_summary=source.stderr, redactions=(), truncated=False,
        output_bytes=len(source.stdout.encode()) + len(source.stderr.encode()), errors=source.errors,
    )


class RecordingDispatcher(LocalAdapterDispatcher):
    def __init__(self, *, result=None, raises=False, supported=None):
        super().__init__()
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "configured_result", result)
        object.__setattr__(self, "raises", raises)
        object.__setattr__(self, "configured_supported", supported)

    def contains(self, operation_name):
        if self.configured_supported is not None:
            return operation_name in self.configured_supported
        return super().contains(operation_name)

    def dispatch(self, contract, now_monotonic):
        self.calls.append((contract, now_monotonic))
        if self.raises:
            raise RuntimeError(r"sensitive C:\\Users\\Private stack")
        if self.configured_result is not None:
            return self.configured_result
        return super().dispatch(contract, now_monotonic)


class FailingValidator:
    def build_contract(self, **kwargs):
        return LocalOperationValidationResult(success=False, errors=("validator blocked", "validator blocked"))


def real_engine():
    policy = replace(DiagnosticLocalExecutorPolicy(), allow_local_execution=True, allow_real_execution=True)
    return DiagnosticSessionEngine(local_operation_validator=SafeLocalOperationValidator(policy=policy))


@pytest.mark.parametrize("log_name", ["System", "Application"])
@pytest.mark.parametrize("hours", [None, 1, 24, 168])
def test_build_event_log_contract_with_structured_arguments(log_name, hours):
    _, source, turn = build(log_name=log_name, hours=hours)
    assert len(turn.session.local_execution_contracts) == 1
    item = turn.session.current_local_execution_contract
    assert item.command.operation_name == "collect_event_logs"
    assert item.command.adapter_type == LocalAdapterType.WINDOWS_EVENT_LOG
    assert item.command.arguments == tuple(
        LocalOperationArgument(parameter.key, parameter.value, required=parameter.required)
        for parameter in source.execution_plan.actions[0].parameters
    )
    assert turn.session.local_raw_results == () and turn.session.local_sanitized_results == ()


def test_missing_required_log_name_is_blocked_before_dispatch():
    dispatcher = RecordingDispatcher(); engine = DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    _, _, turn = build(engine, log_name=None)
    assert turn.session.local_execution_contracts == () and dispatcher.calls == []
    assert "local_execution_errors" in turn.session.metadata


@pytest.mark.parametrize("log_name,hours", [
    ("Security", None), ("Setup", None), ("System", 0), ("System", -1),
    ("System", 169), ("System", "24"),
])
def test_invalid_adapter_level_arguments_build_structurally_but_fail_on_dispatch(log_name, hours):
    engine, _, built = build(log_name=log_name, hours=hours)
    assert built.session.current_local_execution_contract is not None
    turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    assert turn.session.current_local_raw_result.state == LocalExecutionState.FAILED
    assert "local_execution_errors" in turn.session.metadata


@pytest.mark.parametrize("operation", UNSUPPORTED)
def test_session_blocks_operations_not_supported_by_dispatcher(operation):
    source, _ = graph()
    turn = DiagnosticSessionEngine().build_local_execution_contract(
        source, request_id="executor-1", operation_name=operation, command_id="command-1",
        contract_id="contract-1", now_monotonic=10,
    )
    assert turn.session.local_execution_contracts == ()


@pytest.mark.parametrize("log_name", ["System", "Application"])
def test_event_log_dry_run_routes_via_dispatcher_and_stores_results(log_name):
    dispatcher = RecordingDispatcher(); engine = DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    _, source, built, turn = execute(engine, log_name=log_name)
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0][0] == built.current_local_execution_contract
    assert turn.session.current_local_raw_result.state == LocalExecutionState.SUCCESS
    assert turn.session.current_local_sanitized_result.state == LocalExecutionState.SUCCESS
    assert len(turn.session.local_raw_results) == len(turn.session.local_sanitized_results) == 1
    assert turn.session.status == source.status == built.status


def test_dry_run_does_not_access_real_backend(monkeypatch):
    class ForbiddenBackend:
        def __getattr__(self, name):
            raise AssertionError("backend must not be touched")
    monkeypatch.setattr("app.services.diagnostic_engine.local_event_log_adapter._event_log_backend", ForbiddenBackend())
    assert execute()[3].session.current_local_raw_result.state == LocalExecutionState.SUCCESS


def test_real_execution_with_missing_backend_preserves_controlled_failure(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.local_event_log_adapter._event_log_backend", None)
    monkeypatch.setattr("app.services.diagnostic_engine.local_event_log_adapter.platform.system", lambda: "Windows")
    _, source, built, turn = execute(real_engine(), dry_run=False)
    assert turn.session.status == source.status == built.status
    assert turn.session.current_local_raw_result.stderr == "Backend seguro de Event Log indisponível."
    assert turn.session.current_local_sanitized_result.stderr_summary == "Backend seguro de Event Log indisponível."
    assert "local_execution_errors" in turn.session.metadata


def test_default_policy_blocks_real_execution_without_fake_output():
    _, _, built = build(dry_run=False)
    turn = DiagnosticSessionEngine().execute_local_contract(
        built.session, contract_id="contract-1", now_monotonic=11,
    )
    assert turn.session.local_raw_results == () and turn.session.local_sanitized_results == ()
    assert "local_execution_errors" in turn.session.metadata


def test_dispatch_failure_without_results_does_not_invent_snapshots():
    result = LocalAdapterDispatchResult(success=False, errors=("blocked", "blocked"))
    dispatcher = RecordingDispatcher(result=result); engine = DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    _, _, built = build(engine); turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    assert turn.session.local_raw_results == () and turn.session.local_sanitized_results == ()
    assert turn.session.metadata["local_execution_errors"] == ("blocked",)


@pytest.mark.parametrize("include_raw,include_sanitized", [(True, False), (True, True)])
def test_dispatch_failure_preserves_only_results_that_are_present(include_raw, include_sanitized):
    raw_result = raw(LocalExecutionState.FAILED) if include_raw else None
    sanitized_result = sanitized(raw_result) if include_sanitized else None
    _, _, built = build()
    result = LocalAdapterDispatchResult(
        success=False, contract=built.session.current_local_execution_contract,
        raw_result=raw_result, sanitized_result=sanitized_result, errors=("adapter failed",),
    )
    dispatcher = RecordingDispatcher(result=result); engine = DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    _, _, rebuilt = build(engine)
    turn = engine.execute_local_contract(rebuilt.session, contract_id="contract-1", now_monotonic=11)
    assert len(turn.session.local_raw_results) == int(include_raw)
    assert len(turn.session.local_sanitized_results) == int(include_sanitized)


def test_dispatch_exception_is_generic_and_leak_free():
    dispatcher = RecordingDispatcher(raises=True); engine = DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    _, _, built = build(engine); turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=11)
    assert turn.errors == ("Falha na execução local.",)
    assert "private" not in str(turn.session.metadata).lower()
    assert turn.session.local_raw_results == () and turn.session.local_sanitized_results == ()


def test_validator_failure_never_calls_dispatcher_and_deduplicates_errors():
    dispatcher = RecordingDispatcher()
    engine = DiagnosticSessionEngine(
        local_operation_validator=FailingValidator(), local_adapter_dispatcher=dispatcher,
    )
    _, _, turn = build(engine)
    assert dispatcher.calls == [] and turn.session.local_execution_contracts == ()
    assert turn.session.metadata["local_execution_errors"] == ("validator blocked",)


@pytest.mark.parametrize("missing", ["request", "action", "grant"])
def test_missing_authorization_graph_blocks_event_contract(missing):
    engine = DiagnosticSessionEngine(); source, arguments = graph()
    if missing == "request":
        source = replace(source, executor_requests=())
    elif missing == "action":
        source = replace(
            source,
            execution_plan=replace(source.execution_plan, actions=(), current_action_id=None),
        )
    else:
        source = replace(source, approval_grants=())
    turn = engine.build_local_execution_contract(
        source, request_id="executor-1", operation_name="collect_event_logs",
        command_id="command-1", contract_id="contract-1", now_monotonic=10,
        arguments=arguments,
    )
    assert turn.session.local_execution_contracts == ()
    assert "local_execution_errors" in turn.session.metadata


@pytest.mark.parametrize("field,value", [
    ("operation.operation_name", "ping_host"),
    ("command.operation_name", "ping_host"),
    ("operation.adapter_type", LocalAdapterType.PROCESS),
    ("command.adapter_type", LocalAdapterType.UNKNOWN),
    ("operation.operation_type", LocalOperationType.STATE_CHANGING),
    ("command.operation_type", LocalOperationType.DESTRUCTIVE),
    ("command.target", ExecutionTarget.LINUX),
    ("command.target", ExecutionTarget.NETWORK),
    ("command.target", ExecutionTarget.REMOTE_AGENT),
    ("command.risk", ExecutionRisk.MEDIUM),
    ("command.risk", ExecutionRisk.HIGH),
    ("command.risk", ExecutionRisk.CRITICAL),
    ("command.timeout_seconds", 0),
    ("command.timeout_seconds", 31),
    ("command.dry_run", "true"),
])
def test_tampered_event_contract_fails_closed_without_session_fallback(field, value):
    engine, _, built = build(); tampered = deepcopy(built.session.current_local_execution_contract)
    parent, child = field.split("."); object.__setattr__(getattr(tampered, parent), child, value)
    prepared = replace(built.session, local_execution_contracts=(tampered,))
    turn = engine.execute_local_contract(prepared, contract_id="contract-1", now_monotonic=11)
    assert turn.session.local_raw_results == () and turn.session.local_sanitized_results == ()
    assert "local_execution_errors" in turn.session.metadata


@pytest.mark.parametrize("state", [
    LocalExecutionState.BLOCKED, LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS,
    LocalExecutionState.FAILED, LocalExecutionState.CANCELLED, LocalExecutionState.TIMED_OUT,
])
def test_final_event_contract_state_is_blocked(state):
    engine, _, built = build(); tampered = deepcopy(built.session.current_local_execution_contract)
    object.__setattr__(tampered, "state", state)
    prepared = replace(built.session, local_execution_contracts=(tampered,))
    turn = engine.execute_local_contract(prepared, contract_id="contract-1", now_monotonic=11)
    assert turn.session.local_raw_results == () and "local_execution_errors" in turn.session.metadata


@pytest.mark.parametrize("invalid", [-1, True, "11", None])
def test_invalid_execution_timestamp_is_blocked_before_dispatch(invalid):
    dispatcher = RecordingDispatcher(); engine, _, built = build(
        DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    )
    turn = engine.execute_local_contract(built.session, contract_id="contract-1", now_monotonic=invalid)
    assert dispatcher.calls == [] and turn.session.local_raw_results == ()


@pytest.mark.parametrize("subject", ["raw", "sanitized", "dispatcher_registry"])
def test_returned_results_and_dispatcher_registry_remain_immutable(subject):
    dispatcher = RecordingDispatcher(); engine, _, _, turn = execute(
        DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    )
    selected = {
        "raw": turn.session.current_local_raw_result,
        "sanitized": turn.session.current_local_sanitized_result,
        "dispatcher_registry": dispatcher.supported_operations(),
    }[subject]
    before = deepcopy(selected)
    engine.execute_local_contract(turn.session, contract_id="contract-1", now_monotonic=12)
    assert selected == before


@pytest.mark.parametrize("log_name,hours", [
    ("System", None), ("Application", None), ("System", 24), ("System", 48),
])
def test_contract_deduplication_uses_full_event_log_identity(log_name, hours):
    engine, source, first = build(log_name=log_name, hours=hours)
    arguments = first.session.current_local_execution_contract.command.arguments
    duplicate = engine.build_local_execution_contract(
        first.session, request_id="executor-1", operation_name="collect_event_logs",
        command_id="command-1", contract_id="different-id", now_monotonic=11,
        arguments=arguments, dry_run=True,
    )
    assert duplicate.session == first.session and not duplicate.state_changed


def test_system_application_and_hours_are_distinct_contracts():
    engine, _, first = build(log_name="System")
    application_source, application_arguments = graph(log_name="Application")
    application_source = replace(
        application_source, local_execution_contracts=first.session.local_execution_contracts,
    )
    second = engine.build_local_execution_contract(
        application_source, request_id="executor-1", operation_name="collect_event_logs",
        command_id="command-1", contract_id="contract-2", now_monotonic=11,
        arguments=application_arguments,
    )
    assert len(second.session.local_execution_contracts) == 2


def test_event_execution_appends_without_erasing_previous_local_results():
    engine, _, _, first = execute()
    prior_raw = first.session.local_raw_results; prior_sanitized = first.session.local_sanitized_results
    second = engine.execute_local_contract(first.session, contract_id="contract-1", now_monotonic=12)
    assert second.session.local_raw_results[:1] == prior_raw
    assert second.session.local_sanitized_results[:1] == prior_sanitized
    assert len(second.session.local_raw_results) == len(second.session.local_sanitized_results) == 2


@pytest.mark.parametrize("command", ["status", "cancelar", "humano"])
@pytest.mark.parametrize("field", ["local_execution_contracts", "local_raw_results", "local_sanitized_results"])
def test_commands_preserve_event_log_history(command, field):
    engine, _, _, turn = execute(); updated = engine.continue_session(turn.session, command).session
    assert getattr(updated, field) == getattr(turn.session, field)


@pytest.mark.parametrize("field", [
    "local_execution_contracts", "local_raw_results", "local_sanitized_results",
    "current_local_execution_contract", "current_local_raw_result", "current_local_sanitized_result",
])
def test_restart_clears_event_log_history(field):
    engine, _, _, turn = execute(); restarted = engine.restart_session(turn.session, "reiniciar").session
    assert getattr(restarted, field) in ((), None)


@pytest.mark.parametrize("subject", [
    "session", "contract", "request", "action", "grant", "plan", "approval_history",
])
def test_event_dispatch_preserves_previous_snapshots(subject):
    engine, _, built = build(); source = built.session; before = deepcopy(source)
    engine.execute_local_contract(source, contract_id="contract-1", now_monotonic=11)
    mapping = {
        "session": (source, before),
        "contract": (source.current_local_execution_contract, before.current_local_execution_contract),
        "request": (source.executor_requests, before.executor_requests),
        "action": (source.execution_plan.actions, before.execution_plan.actions),
        "grant": (source.approval_grants, before.approval_grants),
        "plan": (source.execution_plan, before.execution_plan),
        "approval_history": (source.approval_requests, before.approval_requests),
    }
    assert mapping[subject][0] == mapping[subject][1]


@pytest.mark.parametrize("operation", ["read_system_information", "check_disk_information", "check_disk_space"])
def test_previous_dispatcher_operations_remain_supported(operation):
    assert DiagnosticSessionEngine().local_adapter_dispatcher.contains(operation)


@pytest.mark.parametrize("forbidden", [
    "hostname", "username", "sid", "domain", "ip_address", "mac_address", "environment",
])
def test_session_does_not_enrich_dispatcher_output(forbidden):
    _, _, _, turn = execute()
    assert forbidden not in turn.session.current_local_raw_result.stdout.lower()
    assert forbidden not in turn.session.current_local_sanitized_result.stdout_summary.lower()


def test_session_stores_dispatcher_output_exactly():
    _, _, built = build(); raw_result = raw(); sanitized_result = sanitized(raw_result)
    result = LocalAdapterDispatchResult(
        success=True, contract=built.session.current_local_execution_contract,
        raw_result=raw_result, sanitized_result=sanitized_result,
    )
    dispatcher = RecordingDispatcher(result=result); engine = DiagnosticSessionEngine(local_adapter_dispatcher=dispatcher)
    _, _, rebuilt = build(engine)
    turn = engine.execute_local_contract(rebuilt.session, contract_id="contract-1", now_monotonic=11)
    assert turn.session.current_local_raw_result == raw_result
    assert turn.session.current_local_sanitized_result == sanitized_result


def test_grant_action_and_session_status_remain_unchanged():
    _, source, built, turn = execute()
    assert turn.session.approval_grants == built.approval_grants == source.approval_grants
    assert turn.session.approval_grants[0].used is False
    assert turn.session.execution_plan.actions[0].status == ExecutionStatus.READY
    assert turn.session.status == built.status == source.status


@pytest.mark.parametrize("name", [
    "win32evtlog", "subprocess", "os", "socket", "requests", "urllib", "httpx", "pathlib",
])
def test_session_engine_has_no_forbidden_operational_imports(name):
    tree = ast.parse(SESSION_ENGINE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "openeventlog", "readeventlog", "closeeventlog", "powershell.exe", "cmd.exe",
    "wevtutil", "wmic", "os.system", "subprocess.run", "socket.socket",
    "requests.get", "httpx.get", "win32evtlog", "local_event_log_adapter",
])
def test_session_local_section_has_no_direct_event_log_access(text):
    source = SESSION_ENGINE.read_text(encoding="utf-8")
    section = source[source.index("def build_local_execution_contract"):source.index("def _status_for")]
    assert text not in section.lower()


def test_session_uses_only_dispatcher_for_event_execution():
    source = SESSION_ENGINE.read_text(encoding="utf-8")
    section = source[source.index("def execute_local_contract"):source.index("def _local_execution_error")]
    assert "local_adapter_dispatcher.dispatch" in section
    assert ".execute(" not in section and ".sanitize(" not in section


@pytest.mark.parametrize("path", [SESSION_ENGINE, SESSION_MODELS, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
