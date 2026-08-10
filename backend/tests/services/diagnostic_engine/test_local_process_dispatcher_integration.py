import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from app.services.diagnostic_engine import (
    LocalAdapterDispatcher, LocalDiskInformationAdapter, LocalEventLogAdapter,
    LocalProcessAdapter, LocalSystemInformationAdapter, LocalWindowsServiceAdapter,
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
    "collect_event_logs", "list_processes", "list_windows_services",
    "read_system_information", "read_system_process_information",
)
PROCESS_OPERATIONS = ("list_processes", "read_system_process_information")
UNSUPPORTED = (
    "check_network_configuration", "ping_host", "check_port", "validate_configuration",
    "terminate_process", "kill_process", "suspend_process", "resume_process",
    "set_process_priority", "set_process_affinity", "create_process", "inject_process",
    "debug_attach", "read_process_memory", "write_process_memory", "unknown",
)


def contract(operation="list_processes", *, dry_run=True, sandbox=None):
    arguments = ()
    if operation == "read_system_process_information":
        arguments = (LocalOperationArgument("process_name", "python.exe", required=True),)
    return SafeLocalOperationCatalog().build_contract(
        contract_id="contract-1", executor_request_id="executor-1",
        execution_plan_id="plan-1", action_id="action-1", grant_id="grant-1",
        operation_name=operation, command_id="command-1", arguments=arguments,
        dry_run=dry_run, sandbox_policy=sandbox,
    )


def raw(state=LocalExecutionState.SUCCESS, command_id="command-1"):
    stdout = '{"operation":"process"}' if state == LocalExecutionState.SUCCESS else ""
    chunk = () if not stdout else (LocalOutputChunk(
        sequence=0, stream=OutputStreamType.STDOUT, content=stdout, truncated=False,
        redacted=False, redaction_reasons=(), occurred_at_monotonic=10,
    ),)
    return LocalRawExecutionResult(
        command_id=command_id, state=state, started_at_monotonic=10,
        finished_at_monotonic=10, exit_code=0 if state == LocalExecutionState.SUCCESS else None,
        stdout=stdout, stderr="" if stdout else "process failure", output_chunks=chunk,
        timed_out=False, cancelled=False,
        errors=() if stdout else ("process failure",),
    )


class ProcessSpy(LocalProcessAdapter):
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
            raise RuntimeError("sensitive process stack")
        return raw(
            LocalExecutionState.FAILED if self.failed else LocalExecutionState.SUCCESS,
            "other-command" if self.bad_id else item.command.command_id,
        )

    def sanitize(self, result):
        self.sanitize_calls.append(result)
        if self.sanitize_error:
            raise RuntimeError("sensitive process sanitizer stack")
        return LocalSanitizedResult(
            command_id=result.command_id, state=result.state, exit_code=result.exit_code,
            stdout_summary=result.stdout, stderr_summary=result.stderr, redactions=(),
            truncated=False,
            output_bytes=len(result.stdout.encode()) + len(result.stderr.encode()),
            errors=result.errors,
        )


def real_policy(**changes):
    return replace(
        DiagnosticLocalExecutorPolicy(), allow_local_execution=True,
        allow_real_execution=True, **changes,
    )


def test_default_constructor_creates_distinct_process_adapters():
    first = LocalAdapterDispatcher(); second = LocalAdapterDispatcher()
    assert isinstance(first.process_adapter, LocalProcessAdapter)
    assert first.process_adapter is not second.process_adapter


def test_custom_process_adapter_and_policy_are_preserved():
    adapter = ProcessSpy(); policy = DiagnosticLocalExecutorPolicy()
    dispatcher = LocalAdapterDispatcher(process_adapter=adapter, policy=policy)
    assert dispatcher.process_adapter is adapter and dispatcher.policy is policy


def test_old_positional_constructor_order_is_preserved():
    system = LocalSystemInformationAdapter(); disk = LocalDiskInformationAdapter()
    policy = DiagnosticLocalExecutorPolicy(); event = LocalEventLogAdapter()
    service = LocalWindowsServiceAdapter()
    dispatcher = LocalAdapterDispatcher(system, disk, policy, event, service)
    assert dispatcher.system_information_adapter is system
    assert dispatcher.disk_information_adapter is disk and dispatcher.policy is policy
    assert dispatcher.event_log_adapter is event and dispatcher.windows_service_adapter is service
    assert isinstance(dispatcher.process_adapter, LocalProcessAdapter)


@pytest.mark.parametrize("invalid", [None, object(), "adapter", 1, True])
def test_invalid_process_adapter_is_rejected(invalid):
    with pytest.raises(ValueError, match="process_adapter"):
        LocalAdapterDispatcher(process_adapter=invalid)


def test_registry_is_immutable_sorted_tuple_with_eight_operations():
    dispatcher = LocalAdapterDispatcher()
    assert isinstance(dispatcher._registry, MappingProxyType)
    assert dispatcher.supported_operations() == OPERATIONS
    assert isinstance(dispatcher.supported_operations(), tuple)
    with pytest.raises(TypeError):
        dispatcher._registry["unknown"] = object()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_contains_all_registered_operations(operation):
    assert LocalAdapterDispatcher().contains(operation)


@pytest.mark.parametrize("operation", UNSUPPORTED + (None, 1, "", "LIST_PROCESSES"))
def test_contains_rejects_unregistered_and_inexact_operations(operation):
    assert not LocalAdapterDispatcher().contains(operation)


@pytest.mark.parametrize("operation", PROCESS_OPERATIONS)
def test_resolve_routes_process_operations_exactly(operation):
    dispatcher = LocalAdapterDispatcher()
    assert dispatcher.resolve(operation) is dispatcher.process_adapter


@pytest.mark.parametrize("operation,field", [
    ("read_system_information", "system_information_adapter"),
    ("check_disk_information", "disk_information_adapter"),
    ("check_disk_space", "disk_information_adapter"),
    ("collect_event_logs", "event_log_adapter"),
    ("list_windows_services", "windows_service_adapter"),
    ("check_service_status", "windows_service_adapter"),
])
def test_resolve_preserves_existing_routes(operation, field):
    dispatcher = LocalAdapterDispatcher()
    assert dispatcher.resolve(operation) is getattr(dispatcher, field)


@pytest.mark.parametrize("operation", UNSUPPORTED + (None, object(), "process", "list_process"))
def test_resolve_has_no_fuzzy_or_fallback_route(operation):
    assert LocalAdapterDispatcher().resolve(operation) is None


@pytest.mark.parametrize("operation", PROCESS_OPERATIONS)
def test_default_policy_delegates_process_dry_run(operation):
    adapter = ProcessSpy()
    result = LocalAdapterDispatcher(process_adapter=adapter).dispatch(contract(operation), 10)
    assert result.success and result.adapter_name == "ProcessSpy"
    assert len(adapter.execute_calls) == len(adapter.sanitize_calls) == 1
    assert result.raw_result is not None and result.sanitized_result is not None
    assert adapter.sanitize_calls[0] == result.raw_result


@pytest.mark.parametrize("operation", PROCESS_OPERATIONS)
@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("adapter_type", [
    LocalAdapterType.UNKNOWN, LocalAdapterType.SYSTEM_INFORMATION,
    LocalAdapterType.DISK_INFORMATION, LocalAdapterType.WINDOWS_EVENT_LOG,
    LocalAdapterType.WINDOWS_SERVICE,
])
def test_wrong_adapter_type_fails_closed(operation, field, adapter_type):
    item = contract(operation); object.__setattr__(getattr(item, field), "adapter_type", adapter_type)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("operation", PROCESS_OPERATIONS)
@pytest.mark.parametrize("target", [
    ExecutionTarget.LOCAL_MACHINE, ExecutionTarget.LINUX, ExecutionTarget.NETWORK,
    ExecutionTarget.REMOTE_AGENT, ExecutionTarget.UNKNOWN,
])
def test_wrong_target_fails_closed(operation, target):
    item = contract(operation); object.__setattr__(item.command, "target", target)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("operation", PROCESS_OPERATIONS)
@pytest.mark.parametrize("risk", [ExecutionRisk.MEDIUM, ExecutionRisk.HIGH, ExecutionRisk.CRITICAL])
def test_wrong_risk_fails_closed(operation, risk):
    item = contract(operation); object.__setattr__(item.command, "risk", risk)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("operation", PROCESS_OPERATIONS)
@pytest.mark.parametrize("kind", [LocalOperationType.STATE_CHANGING, LocalOperationType.DESTRUCTIVE])
@pytest.mark.parametrize("field", ["operation", "command"])
def test_mutable_operation_types_fail_closed(operation, kind, field):
    item = contract(operation); object.__setattr__(getattr(item, field), "operation_type", kind)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("operation", PROCESS_OPERATIONS)
@pytest.mark.parametrize("timeout", [0, -1, 31, 61, True, "30", None])
def test_invalid_timeout_fails_closed(operation, timeout):
    item = contract(operation); object.__setattr__(item.command, "timeout_seconds", timeout)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("field", [
    "allow_shell", "allow_arbitrary_command", "allow_environment_inheritance",
    "allow_network_access", "allow_filesystem_write", "allow_registry_write",
    "allow_service_state_change", "allow_process_termination", "allow_elevation",
    "allow_child_processes",
])
def test_unsafe_sandbox_fails_closed(field):
    item = contract(sandbox=replace(LocalSandboxPolicy(), **{field: True}))
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("field", [
    "allow_process_adapter", "allow_windows_target", "allow_low_risk",
    "allow_read_only_operations", "allow_dry_run",
])
def test_policy_can_block_each_structural_gate(field):
    policy = replace(DiagnosticLocalExecutorPolicy(), **{field: False})
    adapter = ProcessSpy()
    result = LocalAdapterDispatcher(process_adapter=adapter, policy=policy).dispatch(contract(), 10)
    assert not result.success and not adapter.execute_calls


@pytest.mark.parametrize("operation", PROCESS_OPERATIONS)
def test_default_policy_blocks_real_execution_before_adapter(operation):
    adapter = ProcessSpy()
    result = LocalAdapterDispatcher(process_adapter=adapter).dispatch(
        contract(operation, dry_run=False), 10
    )
    assert not result.success and not adapter.execute_calls


@pytest.mark.parametrize("operation", PROCESS_OPERATIONS)
def test_custom_real_policy_delegates_to_process_adapter(operation):
    adapter = ProcessSpy(); policy = real_policy()
    result = LocalAdapterDispatcher(process_adapter=adapter, policy=policy).dispatch(
        contract(operation, dry_run=False), 10
    )
    assert result.success and len(adapter.execute_calls) == 1


def test_missing_backend_message_is_preserved_without_fallback(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.local_process_adapter._process_backend", None)
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_process_adapter.platform.system", lambda: "Windows"
    )
    result = LocalAdapterDispatcher(policy=real_policy()).dispatch(
        contract(dry_run=False), 10
    )
    assert not result.success and result.raw_result is not None
    assert result.raw_result.stderr == "Backend seguro de processos indisponível."


@pytest.mark.parametrize("mode", ["failed", "execute_error", "sanitize_error", "bad_id"])
def test_adapter_and_sanitizer_failures_are_generic(mode):
    adapter = ProcessSpy(**{mode: True})
    result = LocalAdapterDispatcher(process_adapter=adapter).dispatch(contract(), 10)
    assert not result.success and "sensitive" not in " ".join(result.errors).lower()
    if mode == "sanitize_error":
        assert result.raw_result is not None and result.sanitized_result is None


@pytest.mark.parametrize("subject", ["contract", "operation", "command", "sandbox"])
def test_dispatch_preserves_contract_graph(subject):
    item = contract("read_system_process_information")
    selected = {
        "contract": item, "operation": item.operation, "command": item.command,
        "sandbox": item.sandbox_policy,
    }[subject]
    before = deepcopy(selected); LocalAdapterDispatcher().dispatch(item, 10)
    assert selected == before


def test_dispatch_preserves_registry_and_adapter_identity():
    adapter = ProcessSpy(); dispatcher = LocalAdapterDispatcher(process_adapter=adapter)
    before = dispatcher.supported_operations(); dispatcher.dispatch(contract(), 10)
    assert dispatcher.supported_operations() == before
    assert dispatcher.resolve("list_processes") is adapter


@pytest.mark.parametrize("name", ["psutil", "subprocess", "socket", "requests", "httpx"])
def test_dispatcher_has_no_forbidden_operational_import(name):
    tree = ast.parse(DISPATCHER_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "process_iter", "psutil.process", ".terminate(", ".kill(", ".suspend(", ".resume(",
    ".nice(", ".cpu_affinity(", "createprocess", "openprocess", "terminateprocess",
    "powershell.exe", "cmd.exe", "tasklist", "taskkill", "wmic", "subprocess.run",
    "socket.socket", "requests.get", "httpx.get",
])
def test_dispatcher_has_no_process_api_mutation_or_fallback(text):
    assert text not in DISPATCHER_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("path", [DISPATCHER_FILE, PACKAGE_FILE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes()
    assert not content.startswith(b"\xef\xbb\xbf")
    content.decode("utf-8")
