import ast
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    LocalSystemInformationAdapter, SafeLocalOperationValidator,
)
from app.services.diagnostic_engine.approval_models import ApprovalActor, ApprovalType, ApprovedActionGrant
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction, ExecutionPlan, ExecutionResult, ExecutionRisk, ExecutionStatus, ExecutionTarget,
)
from app.services.diagnostic_engine.executor_models import ExecutionContext, ExecutorRequest
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalExecutionState, LocalOperationArgument, LocalOperationType,
    LocalRawExecutionResult, LocalSanitizedResult,
)
from app.services.diagnostic_engine.local_executor_policy import DiagnosticLocalExecutorPolicy
from app.services.diagnostic_engine.local_operation_validator import LocalOperationValidationResult
from app.services.diagnostic_engine.session_engine import DiagnosticSessionEngine
from app.services.diagnostic_engine.session_models import DiagnosticSession, DiagnosticSessionStatus


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
SESSION_ENGINE = ROOT / "app/services/diagnostic_engine/session_engine.py"
SESSION_MODELS = SESSION_ENGINE.with_name("session_models.py")


def action(status=ExecutionStatus.READY, **changes):
    values = dict(
        action_id="action-1", action_name="read_system_information", title="System information",
        description="Read-only structural system information.", target=ExecutionTarget.WINDOWS,
        status=status, risk=ExecutionRisk.LOW, parameters=(), timeout_seconds=30,
        requires_confirmation=False, requires_human=False, metadata={"action_kind": "read_only"},
    )
    values.update(changes)
    return ExecutionAction(**values)


def grant(item=None, **changes):
    item = item or action()
    values = dict(
        grant_id="grant-1", approval_id="approval-1", execution_plan_id="plan-1",
        action_id=item.action_id, action_snapshot=item,
        approved_by=ApprovalActor("actor-1", ApprovalType.HUMAN_TECHNICIAN),
        approved_at_monotonic=1.0, expires_at_monotonic=100.0,
        metadata={"session_id": "session-1"},
    )
    values.update(changes)
    return ApprovedActionGrant(**values)


def request(item=None, grant_item=None):
    item = item or action(); grant_item = grant_item or grant(item)
    context = ExecutionContext(
        session_id="session-1", diagnostic_plan_id="diagnostic-1", execution_plan_id="plan-1",
        action_id=item.action_id, grant_id=grant_item.grant_id, approval_id=grant_item.approval_id,
        target=item.target, risk=item.risk, requested_at_monotonic=2.0,
    )
    return ExecutorRequest(
        request_id="executor-1", context=context, action_snapshot=item,
        grant_snapshot=grant_item, timeout_seconds=30, dry_run=True,
    )


def session(item=None, grant_item=None, request_item=None, **changes):
    item = item or action(); grant_item = grant_item or grant(item); request_item = request_item or request(item, grant_item)
    source_plan = ExecutionPlan("plan-1", ExecutionStatus.READY, (item,), item.action_id)
    values = dict(
        session_id="session-1", status=DiagnosticSessionStatus.READY_FOR_ACTION,
        original_message="Erro", last_message="Erro", execution_plan=source_plan,
        execution_result=ExecutionResult(True, source_plan, item), approval_grants=(grant_item,),
        executor_requests=(request_item,),
    )
    values.update(changes)
    return DiagnosticSession(**values)


def build(subject=None, source=None, **changes):
    values = dict(
        request_id="executor-1", operation_name="read_system_information",
        command_id="command-1", contract_id="contract-1", now_monotonic=10.0,
    )
    values.update(changes)
    return (subject or DiagnosticSessionEngine()).build_local_execution_contract(
        source or session(), **values,
    )


def built(subject=None, source=None, **changes):
    subject = subject or DiagnosticSessionEngine()
    return subject, build(subject, source, **changes).session


def executed(subject=None, source=None, **changes):
    subject, source = built(subject, source, **changes)
    return subject, source, subject.execute_local_contract(source, contract_id="contract-1", now_monotonic=11)


def windows(monkeypatch):
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


def test_session_local_defaults_are_empty():
    source = DiagnosticSession("id", DiagnosticSessionStatus.NEW, "erro", "erro")
    assert source.local_execution_contracts == () and source.local_raw_results == ()
    assert source.local_sanitized_results == ()
    assert source.current_local_execution_contract is None
    assert source.current_local_raw_result is None and source.current_local_sanitized_result is None


@pytest.mark.parametrize(
    ("field_name", "expected"),
    [
        ("local_execution_contracts", ()), ("local_raw_results", ()),
        ("local_sanitized_results", ()), ("current_local_execution_contract", None),
        ("current_local_raw_result", None), ("current_local_sanitized_result", None),
    ],
)
def test_each_local_session_default(field_name, expected):
    source = DiagnosticSession("id", DiagnosticSessionStatus.NEW, "erro", "erro")
    assert getattr(source, field_name) == expected


def test_default_dependencies_are_created():
    subject = DiagnosticSessionEngine()
    assert isinstance(subject.local_operation_validator, SafeLocalOperationValidator)
    assert isinstance(subject.local_system_information_adapter, LocalSystemInformationAdapter)


def test_custom_dependencies_are_injected():
    validator = SafeLocalOperationValidator(); adapter = LocalSystemInformationAdapter()
    subject = DiagnosticSessionEngine(local_operation_validator=validator, local_system_information_adapter=adapter)
    assert subject.local_operation_validator is validator and subject.local_system_information_adapter is adapter


def test_start_session_does_not_create_or_execute_local_operation():
    started = DiagnosticSessionEngine().start_session("Erro de rede", session_id="session-1").session
    assert started.local_execution_contracts == () and started.local_raw_results == ()


def test_continue_session_does_not_create_or_execute_local_operation():
    subject = DiagnosticSessionEngine(); started = subject.start_session("Erro de rede", session_id="session-1").session
    continued = subject.continue_session(started, "Mais detalhes").session
    assert continued.local_execution_contracts == () and continued.local_sanitized_results == ()


@pytest.mark.parametrize("operation", ["start", "continue"])
@pytest.mark.parametrize("field_name", [
    "local_execution_contracts", "local_raw_results", "local_sanitized_results",
    "current_local_execution_contract", "current_local_raw_result", "current_local_sanitized_result",
])
def test_start_and_continue_preserve_each_empty_local_field(operation, field_name):
    subject = DiagnosticSessionEngine()
    started = subject.start_session("Erro de rede", session_id="session-1").session
    selected = started if operation == "start" else subject.continue_session(started, "Detalhes").session
    assert getattr(selected, field_name) in ((), None)


def test_valid_contract_is_stored_without_execution():
    turn = build()
    assert len(turn.session.local_execution_contracts) == 1
    assert turn.session.current_local_execution_contract == turn.session.local_execution_contracts[0]
    assert turn.session.local_raw_results == () and turn.session.local_sanitized_results == ()


@pytest.mark.parametrize("request_id", ["missing", "", None, 1, object()])
def test_missing_request_is_controlled(request_id):
    turn = build(request_id=request_id)
    assert turn.session.local_execution_contracts == ()
    assert turn.session.metadata["local_execution_errors"]


def test_missing_action_is_controlled():
    source = session(execution_plan=ExecutionPlan("plan-1", ExecutionStatus.READY, ()))
    assert build(source=source).session.local_execution_contracts == ()


def test_missing_grant_is_controlled():
    assert build(source=session(approval_grants=())).session.local_execution_contracts == ()


@pytest.mark.parametrize("operation_name", [
    "ping_host", "check_port", "list_processes", "missing", "", "list_windows_services",
    "check_service_status", "collect_event_logs", "check_disk_information", "check_disk_space",
    "check_network_configuration", "validate_configuration",
])
def test_only_system_information_operation_is_accepted(operation_name):
    turn = build(operation_name=operation_name)
    assert turn.session.local_execution_contracts == ()
    assert turn.session.metadata["local_execution_errors"]


def test_explicit_command_contract_ids_and_timeout_are_preserved():
    turn = build(command_id="cmd-9", contract_id="contract-9", timeout_seconds=10)
    contract_item = turn.session.local_execution_contracts[0]
    assert contract_item.contract_id == "contract-9"
    assert contract_item.command.command_id == "cmd-9" and contract_item.command.timeout_seconds == 10


@pytest.mark.parametrize("dry_run", [True, False])
def test_build_contract_dry_run_policy(dry_run):
    turn = build(dry_run=dry_run)
    assert bool(turn.session.local_execution_contracts) is dry_run


def test_custom_policy_allows_real_structural_contract():
    policy = replace(DiagnosticLocalExecutorPolicy(), allow_local_execution=True, allow_real_execution=True)
    subject = DiagnosticSessionEngine(local_operation_validator=SafeLocalOperationValidator(policy=policy))
    assert build(subject, dry_run=False).session.local_execution_contracts[0].command.dry_run is False


def test_equivalent_contract_is_deduplicated():
    subject, first = built(); second = build(subject, first).session
    assert second.local_execution_contracts == first.local_execution_contracts


@pytest.mark.parametrize("change", [
    {"command_id": "command-2"}, {"timeout_seconds": 10}, {"contract_id": "contract-2"},
])
def test_non_equivalent_contracts_can_be_recorded(change):
    subject, first = built(); second = build(subject, first, **change).session
    expected = 1 if set(change) == {"contract_id"} else 2
    assert len(second.local_execution_contracts) == expected


class FailingValidator:
    def build_contract(self, **kwargs):
        return LocalOperationValidationResult(success=False, errors=("validator blocked",))


class RaisingValidator:
    def build_contract(self, **kwargs):
        raise RuntimeError("sensitive validator stack")


@pytest.mark.parametrize("validator", [FailingValidator(), RaisingValidator()])
def test_validator_failure_is_controlled_and_adapter_is_not_called(validator):
    class NeverAdapter:
        def execute(self, *args): raise AssertionError("adapter must not execute")
    subject = DiagnosticSessionEngine(
        local_operation_validator=validator, local_system_information_adapter=NeverAdapter(),
    )
    turn = build(subject)
    assert turn.session.local_execution_contracts == ()
    assert turn.session.metadata["local_execution_errors"]


def test_dry_run_results_are_stored_and_current_fields_updated():
    _, _, turn = executed()
    source = turn.session
    assert len(source.local_raw_results) == len(source.local_sanitized_results) == 1
    assert source.current_local_raw_result == source.local_raw_results[-1]
    assert source.current_local_sanitized_result == source.local_sanitized_results[-1]
    assert source.current_local_execution_contract == source.local_execution_contracts[-1]


@pytest.mark.parametrize("field_name", [
    "local_execution_contracts", "local_raw_results", "local_sanitized_results",
    "current_local_execution_contract", "current_local_raw_result", "current_local_sanitized_result",
])
def test_each_local_result_field_is_populated_after_dry_run(field_name):
    value = getattr(executed()[2].session, field_name)
    assert value is not None and value != ()


def test_dry_run_message_is_explicit():
    _, _, turn = executed()
    assert "nenhuma coleta real" in turn.response_message.lower()
    assert "nenhuma coleta real" in turn.session.current_local_raw_result.stdout.lower()


def test_dry_run_does_not_collect_system(monkeypatch):
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_system_information_adapter.platform.system",
        lambda: (_ for _ in ()).throw(AssertionError("must not collect")),
    )
    assert executed()[2].session.current_local_raw_result.state == LocalExecutionState.SUCCESS


@pytest.mark.parametrize("status", [ExecutionStatus.PENDING, ExecutionStatus.READY])
def test_action_status_is_preserved(status):
    item = action(status); source = session(item=item)
    _, _, turn = executed(source=source)
    assert turn.session.execution_plan.actions[0].status == status
    assert turn.session.execution_plan.completed_actions == ()


def test_grant_is_not_consumed():
    _, source, turn = executed(); assert source.approval_grants[0].used is False
    assert turn.session.approval_grants == source.approval_grants
    assert turn.session.approval_grants[0].used is False


def test_session_status_is_not_changed_by_local_flow():
    source = session(); _, built_source = built(source=source); executed_turn = DiagnosticSessionEngine().execute_local_contract
    subject = DiagnosticSessionEngine(); built_source = build(subject, source).session
    turn = subject.execute_local_contract(built_source, contract_id="contract-1", now_monotonic=11)
    assert turn.session.status == source.status


def test_real_system_information_is_explicit_and_sanitized(monkeypatch):
    windows(monkeypatch)
    policy = replace(DiagnosticLocalExecutorPolicy(), allow_local_execution=True, allow_real_execution=True)
    subject = DiagnosticSessionEngine(local_operation_validator=SafeLocalOperationValidator(policy=policy))
    subject, built_source = built(subject, dry_run=False)
    turn = subject.execute_local_contract(built_source, contract_id="contract-1", now_monotonic=11)
    raw_data = json.loads(turn.session.current_local_raw_result.stdout)
    safe_data = json.loads(turn.session.current_local_sanitized_result.stdout_summary)
    assert raw_data["operating_system"] == "Windows" and raw_data["architecture"] == "AMD64"
    assert raw_data["cpu_count"] == 8 and safe_data["python_platform"] == "win32"
    assert "username" not in safe_data and "ip" not in safe_data and "mac" not in safe_data
    assert "HOST-PRIVATE" not in turn.session.current_local_sanitized_result.stdout_summary


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("adapter_type", LocalAdapterType.PROCESS),
        ("target", ExecutionTarget.NETWORK),
        ("risk", ExecutionRisk.MEDIUM),
        ("operation_type", LocalOperationType.STATE_CHANGING),
    ],
)
def test_tampered_contract_is_blocked(field_name, value):
    subject, source = built(); contract_item = deepcopy(source.local_execution_contracts[0])
    object.__setattr__(contract_item.command, field_name, value)
    prepared = replace(source, local_execution_contracts=(contract_item,))
    turn = subject.execute_local_contract(prepared, contract_id="contract-1", now_monotonic=11)
    assert turn.session.local_raw_results == () and turn.session.metadata["local_execution_errors"]


def test_tampered_arguments_are_blocked():
    subject, source = built(); contract_item = deepcopy(source.local_execution_contracts[0])
    object.__setattr__(contract_item.command, "arguments", (LocalOperationArgument("extra", "x"),))
    prepared = replace(source, local_execution_contracts=(contract_item,))
    assert subject.execute_local_contract(prepared, contract_id="contract-1", now_monotonic=11).session.local_raw_results == ()


def test_tampered_sandbox_is_blocked():
    subject, source = built(); contract_item = deepcopy(source.local_execution_contracts[0])
    object.__setattr__(contract_item.sandbox_policy, "allow_shell", True)
    prepared = replace(source, local_execution_contracts=(contract_item,))
    turn = subject.execute_local_contract(prepared, contract_id="contract-1", now_monotonic=11)
    assert turn.session.current_local_raw_result is None or turn.session.current_local_raw_result.state == LocalExecutionState.FAILED


@pytest.mark.parametrize("missing", ["request", "action", "grant"])
def test_execution_revalidates_session_history(missing):
    subject, source = built()
    if missing == "request": source = replace(source, executor_requests=())
    elif missing == "action": source = replace(source, execution_plan=ExecutionPlan("plan-1", ExecutionStatus.READY, ()))
    else: source = replace(source, approval_grants=())
    turn = subject.execute_local_contract(source, contract_id="contract-1", now_monotonic=11)
    assert turn.session.local_raw_results == ()


@pytest.mark.parametrize("grant_change", [{"used": True}, {"expires_at_monotonic": 11.0}])
def test_execution_revalidates_grant_state(grant_change):
    subject, source = built(); old = source.approval_grants[0]
    changed = replace(old, **grant_change); source = replace(source, approval_grants=(changed,))
    turn = subject.execute_local_contract(source, contract_id="contract-1", now_monotonic=11)
    assert turn.session.local_raw_results == ()


class FailedAdapter:
    def execute(self, contract, now):
        return LocalRawExecutionResult(
            command_id=contract.command.command_id, state=LocalExecutionState.FAILED,
            started_at_monotonic=now, finished_at_monotonic=now, exit_code=None,
            stdout="", stderr="controlled", output_chunks=(), timed_out=False, cancelled=False,
            errors=("controlled",),
        )
    def sanitize(self, raw):
        return LocalSanitizedResult(
            command_id=raw.command_id, state=raw.state, exit_code=None,
            stdout_summary="", stderr_summary="controlled", redactions=(),
            truncated=False, output_bytes=10, errors=raw.errors,
        )


class RaisingAdapter:
    def execute(self, contract, now): raise RuntimeError("sensitive stack")
    def sanitize(self, raw): raise RuntimeError("sensitive sanitize stack")


@pytest.mark.parametrize("adapter", [FailedAdapter(), RaisingAdapter()])
def test_adapter_failure_is_stored_without_breaking_session(adapter):
    subject = DiagnosticSessionEngine(local_system_information_adapter=adapter)
    _, source = built(subject); turn = subject.execute_local_contract(source, contract_id="contract-1", now_monotonic=11)
    assert turn.session.current_local_raw_result.state == LocalExecutionState.FAILED
    assert turn.session.current_local_sanitized_result.state == LocalExecutionState.FAILED
    assert turn.session.status == source.status
    assert "sensitive" not in turn.response_message.lower()


def test_each_explicit_execution_appends_result_snapshots():
    subject, source = built(); first = subject.execute_local_contract(source, contract_id="contract-1", now_monotonic=11).session
    second = subject.execute_local_contract(first, contract_id="contract-1", now_monotonic=12).session
    assert len(second.local_raw_results) == len(second.local_sanitized_results) == 2
    assert first.local_raw_results == second.local_raw_results[:1]


@pytest.mark.parametrize("field_name", [
    "local_execution_contracts", "local_raw_results", "local_sanitized_results",
])
def test_local_collections_are_defensively_copied(field_name):
    _, _, turn = executed(); source = turn.session; values = list(getattr(source, field_name))
    copied = replace(source, **{field_name: values}); values.clear()
    assert getattr(copied, field_name) == getattr(source, field_name)
    assert getattr(copied, field_name) is not getattr(source, field_name)


@pytest.mark.parametrize("subject_name", [
    "session", "request", "action", "grant", "contract", "raw", "sanitized", "execution_plan",
    "approval_history", "memory",
])
def test_previous_snapshots_are_immutable(subject_name):
    subject, source = built(); before = deepcopy(source)
    turn = subject.execute_local_contract(source, contract_id="contract-1", now_monotonic=11)
    assert source == before
    mapping = {
        "session": source, "request": source.executor_requests[0], "action": source.execution_plan.actions[0],
        "grant": source.approval_grants[0], "contract": source.local_execution_contracts[0],
        "raw": turn.session.local_raw_results[0], "sanitized": turn.session.local_sanitized_results[0],
        "execution_plan": source.execution_plan, "approval_history": source.approval_grants,
        "memory": source.memory_snapshot,
    }
    assert mapping[subject_name] == deepcopy(mapping[subject_name])


@pytest.mark.parametrize("command", ["status", "cancelar", "humano"])
def test_session_commands_preserve_local_history(command):
    subject, _, turn = executed(); source = turn.session
    updated = subject.continue_session(source, command).session
    assert updated.local_execution_contracts == source.local_execution_contracts
    assert updated.local_raw_results == source.local_raw_results


@pytest.mark.parametrize("command", ["status", "cancelar", "humano"])
@pytest.mark.parametrize("field_name", [
    "local_execution_contracts", "local_raw_results", "local_sanitized_results",
])
def test_each_session_command_preserves_each_local_collection(command, field_name):
    subject, _, turn = executed(); source = turn.session
    updated = subject.continue_session(source, command).session
    assert getattr(updated, field_name) == getattr(source, field_name)


def test_local_execution_does_not_change_existing_executor_audit_history():
    subject, source = built(); before = deepcopy(source.execution_audit_trails)
    updated = subject.execute_local_contract(source, contract_id="contract-1", now_monotonic=11).session
    assert updated.execution_audit_trails == before


def test_restart_clears_local_history():
    subject, _, turn = executed(); restarted = subject.restart_session(turn.session, "reiniciar").session
    assert restarted.local_execution_contracts == () and restarted.local_raw_results == ()
    assert restarted.local_sanitized_results == ()
    assert restarted.current_local_execution_contract is None


def test_build_and_dry_run_are_deterministic():
    assert build().session == build().session
    assert executed()[2].session.current_local_sanitized_result == executed()[2].session.current_local_sanitized_result


def test_public_import_compatibility():
    from app.services.diagnostic_engine import DiagnosticSessionEngine as PublicSession
    from app.services.diagnostic_engine import LocalSystemInformationAdapter as PublicAdapter
    assert PublicSession is DiagnosticSessionEngine and PublicAdapter is LocalSystemInformationAdapter


@pytest.mark.parametrize("name", ["subprocess", "os", "socket", "requests", "httpx", "pathlib"])
def test_session_integration_has_no_operational_imports(name):
    tree = ast.parse(SESSION_ENGINE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


def test_session_integration_has_no_grant_consumption_in_local_methods():
    source = SESSION_ENGINE.read_text(encoding="utf-8")
    local_section = source[source.index("def build_local_execution_contract"):source.index("def _status_for")]
    assert "consume_grant" not in local_section and "os.system" not in local_section


@pytest.mark.parametrize("path", [SESSION_ENGINE, SESSION_MODELS, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
