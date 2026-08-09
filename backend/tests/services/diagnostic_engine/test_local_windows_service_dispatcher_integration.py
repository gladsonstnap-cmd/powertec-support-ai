import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from app.services.diagnostic_engine import (
    LocalAdapterDispatcher, LocalDiskInformationAdapter, LocalEventLogAdapter,
    LocalSystemInformationAdapter, LocalWindowsServiceAdapter,
)
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalExecutionState, LocalOperationArgument, LocalOperationType,
    LocalOutputChunk, LocalRawExecutionResult, LocalSandboxPolicy, LocalSanitizedResult,
    OutputStreamType,
)
from app.services.diagnostic_engine.local_executor_policy import DiagnosticLocalExecutorPolicy
from app.services.diagnostic_engine.local_operation_catalog import SafeLocalOperationCatalog


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
DISPATCHER_FILE = ROOT / "app/services/diagnostic_engine/local_adapter_dispatcher.py"
PACKAGE_FILE = DISPATCHER_FILE.with_name("__init__.py")
OPERATIONS = (
    "check_disk_information", "check_disk_space", "check_service_status",
    "collect_event_logs", "list_windows_services", "read_system_information",
)
SERVICE_OPERATIONS = ("list_windows_services", "check_service_status")
UNSUPPORTED = (
    "list_processes", "read_system_process_information", "check_network_configuration",
    "ping_host", "check_port", "validate_configuration", "start_service",
    "stop_service", "restart_service", "pause_service", "resume_service",
    "change_service_startup_type", "install_service", "remove_service", "unknown",
)


def contract(operation="list_windows_services", *, dry_run=True, sandbox=None):
    arguments = ()
    if operation == "check_service_status":
        arguments = (LocalOperationArgument("service_name", "Spooler"),)
    return SafeLocalOperationCatalog().build_contract(
        contract_id="contract-1", executor_request_id="executor-1",
        execution_plan_id="plan-1", action_id="action-1", grant_id="grant-1",
        operation_name=operation, command_id="command-1", arguments=arguments,
        dry_run=dry_run, sandbox_policy=sandbox,
    )


def raw(state=LocalExecutionState.SUCCESS, command_id="command-1", stderr=""):
    stdout = '{"operation":"windows_service"}' if state == LocalExecutionState.SUCCESS else ""
    chunks = () if not stdout else (LocalOutputChunk(
        sequence=0, stream=OutputStreamType.STDOUT, content=stdout, truncated=False,
        redacted=False, redaction_reasons=(), occurred_at_monotonic=10,
    ),)
    return LocalRawExecutionResult(
        command_id=command_id, state=state, started_at_monotonic=10,
        finished_at_monotonic=10, exit_code=0 if state == LocalExecutionState.SUCCESS else None,
        stdout=stdout, stderr=stderr, output_chunks=chunks, timed_out=False,
        cancelled=False, errors=() if not stderr else (stderr,),
    )


class WindowsServiceSpy(LocalWindowsServiceAdapter):
    def __init__(self, *, failed=False, execute_error=False, sanitize_error=False, bad_id=False):
        object.__setattr__(self, "execute_calls", [])
        object.__setattr__(self, "sanitize_calls", [])
        object.__setattr__(self, "failed", failed)
        object.__setattr__(self, "execute_error", execute_error)
        object.__setattr__(self, "sanitize_error", sanitize_error)
        object.__setattr__(self, "bad_id", bad_id)

    def execute(self, item, now):
        self.execute_calls.append((item, now))
        if self.execute_error:
            raise RuntimeError("sensitive service stack")
        return raw(
            LocalExecutionState.FAILED if self.failed else LocalExecutionState.SUCCESS,
            "other-command" if self.bad_id else item.command.command_id,
            "service failure" if self.failed else "",
        )

    def sanitize(self, result):
        self.sanitize_calls.append(result)
        if self.sanitize_error:
            raise RuntimeError("sensitive sanitizer stack")
        return LocalSanitizedResult(
            command_id=result.command_id, state=result.state, exit_code=result.exit_code,
            stdout_summary=result.stdout, stderr_summary=result.stderr, redactions=(),
            truncated=False,
            output_bytes=len(result.stdout.encode()) + len(result.stderr.encode()),
            errors=result.errors,
        )


def allowed_policy(**changes):
    return replace(
        DiagnosticLocalExecutorPolicy(), allow_windows_service_adapter=True, **changes
    )


def test_default_constructor_creates_distinct_windows_service_adapters():
    first = LocalAdapterDispatcher(); second = LocalAdapterDispatcher()
    assert isinstance(first.windows_service_adapter, LocalWindowsServiceAdapter)
    assert first.windows_service_adapter is not second.windows_service_adapter


def test_custom_adapter_and_policy_are_preserved():
    adapter = WindowsServiceSpy(); policy = allowed_policy()
    dispatcher = LocalAdapterDispatcher(windows_service_adapter=adapter, policy=policy)
    assert dispatcher.windows_service_adapter is adapter and dispatcher.policy is policy


def test_old_positional_constructor_order_is_preserved():
    system = LocalSystemInformationAdapter(); disk = LocalDiskInformationAdapter()
    policy = DiagnosticLocalExecutorPolicy(); event = LocalEventLogAdapter()
    dispatcher = LocalAdapterDispatcher(system, disk, policy, event)
    assert dispatcher.system_information_adapter is system
    assert dispatcher.disk_information_adapter is disk
    assert dispatcher.policy is policy and dispatcher.event_log_adapter is event
    assert isinstance(dispatcher.windows_service_adapter, LocalWindowsServiceAdapter)


@pytest.mark.parametrize("invalid", [None, object(), "adapter", 1, True])
def test_invalid_windows_service_adapter_is_rejected(invalid):
    with pytest.raises(ValueError, match="windows_service_adapter"):
        LocalAdapterDispatcher(windows_service_adapter=invalid)


def test_registry_is_immutable_sorted_tuple_with_six_operations():
    dispatcher = LocalAdapterDispatcher()
    assert isinstance(dispatcher._registry, MappingProxyType)
    assert dispatcher.supported_operations() == OPERATIONS
    assert isinstance(dispatcher.supported_operations(), tuple)
    with pytest.raises(TypeError):
        dispatcher._registry["unknown"] = object()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_contains_all_registered_operations(operation):
    assert LocalAdapterDispatcher().contains(operation)


@pytest.mark.parametrize("operation", UNSUPPORTED + (None, 1, "", "LIST_WINDOWS_SERVICES"))
def test_contains_rejects_unregistered_and_inexact_operations(operation):
    assert not LocalAdapterDispatcher().contains(operation)


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
def test_resolve_routes_service_operations_exactly(operation):
    dispatcher = LocalAdapterDispatcher()
    assert dispatcher.resolve(operation) is dispatcher.windows_service_adapter


@pytest.mark.parametrize("operation,field", [
    ("read_system_information", "system_information_adapter"),
    ("check_disk_information", "disk_information_adapter"),
    ("check_disk_space", "disk_information_adapter"),
    ("collect_event_logs", "event_log_adapter"),
])
def test_resolve_preserves_existing_routes(operation, field):
    dispatcher = LocalAdapterDispatcher()
    assert dispatcher.resolve(operation) is getattr(dispatcher, field)


@pytest.mark.parametrize("operation", UNSUPPORTED + (None, object(), "service", "windows_service"))
def test_resolve_has_no_fuzzy_or_fallback_route(operation):
    assert LocalAdapterDispatcher().resolve(operation) is None


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
def test_default_policy_blocks_windows_service_dispatch(operation):
    adapter = WindowsServiceSpy()
    result = LocalAdapterDispatcher(windows_service_adapter=adapter).dispatch(contract(operation), 10)
    assert not result.success and not adapter.execute_calls
    assert result.errors == ("Policy local bloqueou o contrato.",)


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
def test_custom_policy_delegates_dry_run_to_same_adapter(operation):
    adapter = WindowsServiceSpy()
    result = LocalAdapterDispatcher(
        windows_service_adapter=adapter, policy=allowed_policy()
    ).dispatch(contract(operation), 10)
    assert result.success and result.adapter_name == "WindowsServiceSpy"
    assert len(adapter.execute_calls) == len(adapter.sanitize_calls) == 1
    assert result.raw_result is not None and result.sanitized_result is not None
    assert adapter.sanitize_calls[0] == result.raw_result


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("adapter_type", [
    LocalAdapterType.UNKNOWN, LocalAdapterType.SYSTEM_INFORMATION,
    LocalAdapterType.DISK_INFORMATION, LocalAdapterType.WINDOWS_EVENT_LOG,
])
def test_wrong_adapter_type_fails_closed(operation, field, adapter_type):
    item = contract(operation); object.__setattr__(getattr(item, field), "adapter_type", adapter_type)
    assert not LocalAdapterDispatcher(policy=allowed_policy()).dispatch(item, 10).success


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
@pytest.mark.parametrize("target", [
    ExecutionTarget.LOCAL_MACHINE, ExecutionTarget.LINUX, ExecutionTarget.NETWORK,
    ExecutionTarget.REMOTE_AGENT, ExecutionTarget.UNKNOWN,
])
def test_wrong_target_fails_closed(operation, target):
    item = contract(operation); object.__setattr__(item.command, "target", target)
    assert not LocalAdapterDispatcher(policy=allowed_policy()).dispatch(item, 10).success


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
@pytest.mark.parametrize("risk", [ExecutionRisk.MEDIUM, ExecutionRisk.HIGH, ExecutionRisk.CRITICAL])
def test_wrong_risk_fails_closed(operation, risk):
    item = contract(operation); object.__setattr__(item.command, "risk", risk)
    assert not LocalAdapterDispatcher(policy=allowed_policy()).dispatch(item, 10).success


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
@pytest.mark.parametrize("kind", [LocalOperationType.STATE_CHANGING, LocalOperationType.DESTRUCTIVE])
@pytest.mark.parametrize("field", ["operation", "command"])
def test_mutable_operation_types_fail_closed(operation, kind, field):
    item = contract(operation); object.__setattr__(getattr(item, field), "operation_type", kind)
    assert not LocalAdapterDispatcher(policy=allowed_policy()).dispatch(item, 10).success


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
@pytest.mark.parametrize("timeout", [0, -1, 31, 61, True, "30", None])
def test_invalid_timeout_fails_closed(operation, timeout):
    item = contract(operation); object.__setattr__(item.command, "timeout_seconds", timeout)
    assert not LocalAdapterDispatcher(policy=allowed_policy()).dispatch(item, 10).success


@pytest.mark.parametrize("field", [
    "allow_shell", "allow_arbitrary_command", "allow_environment_inheritance",
    "allow_network_access", "allow_filesystem_write", "allow_registry_write",
    "allow_service_state_change", "allow_process_termination", "allow_elevation",
    "allow_child_processes",
])
def test_unsafe_sandbox_fails_closed(field):
    item = contract(sandbox=replace(LocalSandboxPolicy(), **{field: True}))
    assert not LocalAdapterDispatcher(policy=allowed_policy()).dispatch(item, 10).success


@pytest.mark.parametrize("state", [
    LocalExecutionState.BLOCKED, LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS,
    LocalExecutionState.FAILED, LocalExecutionState.CANCELLED, LocalExecutionState.TIMED_OUT,
])
def test_invalid_contract_state_fails_closed(state):
    item = contract(); object.__setattr__(item, "state", state)
    assert not LocalAdapterDispatcher(policy=allowed_policy()).dispatch(item, 10).success


@pytest.mark.parametrize("field", [
    "allow_windows_service_adapter", "allow_windows_target", "allow_low_risk",
    "allow_read_only_operations", "allow_dry_run",
])
def test_custom_policy_still_enforces_each_structural_gate(field):
    policy = replace(allowed_policy(), **{field: False})
    assert not LocalAdapterDispatcher(policy=policy).dispatch(contract(), 10).success


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
def test_real_execution_requires_both_real_execution_flags(operation):
    adapter = WindowsServiceSpy()
    for policy in (
        allowed_policy(allow_local_execution=False, allow_real_execution=True),
        allowed_policy(allow_local_execution=True, allow_real_execution=False),
    ):
        assert not LocalAdapterDispatcher(
            windows_service_adapter=adapter, policy=policy
        ).dispatch(contract(operation, dry_run=False), 10).success
    assert not adapter.execute_calls


@pytest.mark.parametrize("operation", SERVICE_OPERATIONS)
def test_real_execution_can_be_structurally_delegated(operation):
    adapter = WindowsServiceSpy()
    policy = allowed_policy(allow_local_execution=True, allow_real_execution=True)
    result = LocalAdapterDispatcher(
        windows_service_adapter=adapter, policy=policy
    ).dispatch(contract(operation, dry_run=False), 10)
    assert result.success and len(adapter.execute_calls) == 1


def test_missing_backend_message_is_preserved_without_fallback():
    policy = allowed_policy(allow_local_execution=True, allow_real_execution=True)
    result = LocalAdapterDispatcher(policy=policy).dispatch(contract(dry_run=False), 10)
    assert not result.success and result.raw_result is not None
    assert "Backend seguro de serviços do Windows indisponível." in result.raw_result.stderr


@pytest.mark.parametrize("mode", ["failed", "execute_error", "sanitize_error", "bad_id"])
def test_adapter_and_sanitizer_failures_are_generic(mode):
    adapter = WindowsServiceSpy(**{mode: True})
    result = LocalAdapterDispatcher(
        windows_service_adapter=adapter, policy=allowed_policy()
    ).dispatch(contract(), 10)
    assert not result.success and "sensitive" not in " ".join(result.errors).lower()
    if mode == "sanitize_error":
        assert result.raw_result is not None and result.sanitized_result is None


@pytest.mark.parametrize("subject", ["contract", "operation", "command", "sandbox"])
def test_dispatch_preserves_contract_graph(subject):
    item = contract(); selected = {
        "contract": item, "operation": item.operation, "command": item.command,
        "sandbox": item.sandbox_policy,
    }[subject]
    before = deepcopy(selected)
    LocalAdapterDispatcher(policy=allowed_policy()).dispatch(item, 10)
    assert selected == before


def test_dispatch_preserves_registry_and_adapter_identity():
    adapter = WindowsServiceSpy(); dispatcher = LocalAdapterDispatcher(
        windows_service_adapter=adapter, policy=allowed_policy()
    )
    before = dispatcher.supported_operations(); dispatcher.dispatch(contract(), 10)
    assert dispatcher.supported_operations() == before
    assert dispatcher.resolve("list_windows_services") is adapter


@pytest.mark.parametrize("name", [
    "win32service", "win32serviceutil", "subprocess", "socket", "requests", "httpx",
])
def test_dispatcher_has_no_forbidden_operational_import(name):
    tree = ast.parse(DISPATCHER_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "openscmanager", "openservice(", "enumservicesstatus", "queryservicestatus",
    "queryserviceconfig", "startservice(", "controlservice(", "changeserviceconfig(",
    "createservice(", "deleteservice(", "powershell.exe", "cmd.exe", "sc.exe",
    "net.exe", "wmic", "subprocess.run", "socket.socket", "requests.get", "httpx.get",
])
def test_dispatcher_has_no_service_api_or_forbidden_call(text):
    assert text not in DISPATCHER_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("path", [DISPATCHER_FILE, PACKAGE_FILE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes()
    assert not content.startswith(b"\xef\xbb\xbf")
    content.decode("utf-8")
