import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from app.services.diagnostic_engine import (
    LocalAdapterDispatcher, LocalAdapterDispatchResult, LocalDiskInformationAdapter,
    LocalEventLogAdapter, LocalSystemInformationAdapter,
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
PACKAGE = DISPATCHER_FILE.with_name("__init__.py")
OPERATIONS = (
    "check_disk_information", "check_disk_space", "check_service_status",
    "collect_event_logs", "list_processes", "list_windows_services",
    "read_system_information", "read_system_process_information",
)
UNSUPPORTED = (
    "check_network_configuration", "ping_host", "check_port", "validate_configuration", "unknown",
)


def contract(*, dry_run=True, log_name="System", hours=None, sandbox=None):
    arguments = [LocalOperationArgument("log_name", log_name)]
    if hours is not None:
        arguments.append(LocalOperationArgument("hours", hours))
    return SafeLocalOperationCatalog().build_contract(
        contract_id="contract-1", executor_request_id="executor-1", execution_plan_id="plan-1",
        action_id="action-1", grant_id="grant-1", operation_name="collect_event_logs",
        command_id="command-1", arguments=tuple(arguments), dry_run=dry_run,
        sandbox_policy=sandbox,
    )


def raw(state=LocalExecutionState.SUCCESS, command_id="command-1"):
    output = "event-output" if state == LocalExecutionState.SUCCESS else ""
    chunk = LocalOutputChunk(
        sequence=0, stream=OutputStreamType.STDOUT, content=output, truncated=False,
        redacted=False, redaction_reasons=(), occurred_at_monotonic=10,
    )
    return LocalRawExecutionResult(
        command_id=command_id, state=state, started_at_monotonic=10,
        finished_at_monotonic=10, exit_code=0 if state == LocalExecutionState.SUCCESS else None,
        stdout=output, stderr="" if state == LocalExecutionState.SUCCESS else "event failure",
        output_chunks=(chunk,) if output else (), timed_out=False, cancelled=False,
        errors=() if state == LocalExecutionState.SUCCESS else ("event failure",),
    )


class EventSpy(LocalEventLogAdapter):
    def __init__(self, *, failure=False, execute_error=False, sanitize_error=False, bad_id=False):
        object.__setattr__(self, "execute_calls", [])
        object.__setattr__(self, "sanitize_calls", [])
        object.__setattr__(self, "failure", failure)
        object.__setattr__(self, "execute_error", execute_error)
        object.__setattr__(self, "sanitize_error", sanitize_error)
        object.__setattr__(self, "bad_id", bad_id)

    def execute(self, item, now):
        self.execute_calls.append((item, now))
        if self.execute_error:
            raise RuntimeError("sensitive event stack")
        return raw(
            LocalExecutionState.FAILED if self.failure else LocalExecutionState.SUCCESS,
            "other" if self.bad_id else "command-1",
        )

    def sanitize(self, result):
        self.sanitize_calls.append(result)
        if self.sanitize_error:
            raise RuntimeError("sensitive sanitizer stack")
        return LocalSanitizedResult(
            command_id=result.command_id, state=result.state, exit_code=result.exit_code,
            stdout_summary=result.stdout, stderr_summary=result.stderr, redactions=(),
            truncated=False, output_bytes=len(result.stdout.encode()) + len(result.stderr.encode()),
            errors=result.errors,
        )


def test_default_constructor_creates_distinct_event_adapters():
    first = LocalAdapterDispatcher(); second = LocalAdapterDispatcher()
    assert isinstance(first.event_log_adapter, LocalEventLogAdapter)
    assert first.event_log_adapter is not second.event_log_adapter


def test_custom_event_adapter_and_policy_are_preserved():
    adapter = EventSpy(); policy = DiagnosticLocalExecutorPolicy()
    dispatcher = LocalAdapterDispatcher(event_log_adapter=adapter, policy=policy)
    assert dispatcher.event_log_adapter is adapter and dispatcher.policy is policy


def test_old_positional_constructor_order_is_preserved():
    system = LocalSystemInformationAdapter(); disk = LocalDiskInformationAdapter()
    policy = DiagnosticLocalExecutorPolicy()
    dispatcher = LocalAdapterDispatcher(system, disk, policy)
    assert dispatcher.system_information_adapter is system
    assert dispatcher.disk_information_adapter is disk and dispatcher.policy is policy


@pytest.mark.parametrize("invalid", [None, object(), "adapter", 1])
def test_invalid_custom_event_adapter_is_rejected(invalid):
    with pytest.raises(ValueError, match="event_log_adapter"):
        LocalAdapterDispatcher(event_log_adapter=invalid)


def test_registry_is_immutable_and_contains_four_operations():
    dispatcher = LocalAdapterDispatcher()
    assert isinstance(dispatcher._registry, MappingProxyType)
    assert dispatcher.supported_operations() == OPERATIONS
    with pytest.raises(TypeError): dispatcher._registry["ping_host"] = object()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_contains_each_registered_operation(operation):
    assert LocalAdapterDispatcher().contains(operation)


@pytest.mark.parametrize("operation", UNSUPPORTED)
def test_contains_unsupported_operation_is_false(operation):
    assert not LocalAdapterDispatcher().contains(operation)


def test_resolve_event_log_exactly():
    dispatcher = LocalAdapterDispatcher()
    assert dispatcher.resolve("collect_event_logs") is dispatcher.event_log_adapter


def test_resolve_existing_system_and_disk_routes_are_unchanged():
    dispatcher = LocalAdapterDispatcher()
    assert dispatcher.resolve("read_system_information") is dispatcher.system_information_adapter
    assert dispatcher.resolve("check_disk_information") is dispatcher.disk_information_adapter
    assert dispatcher.resolve("check_disk_space") is dispatcher.disk_information_adapter


@pytest.mark.parametrize("value", [None, object(), "", "collect_event", "event_logs", "COLLECT_EVENT_LOGS"])
def test_resolve_unknown_has_no_fallback(value):
    assert LocalAdapterDispatcher().resolve(value) is None


def test_event_dry_run_dispatches_and_sanitizes_with_default_adapter():
    result = LocalAdapterDispatcher().dispatch(contract(), 10)
    assert result.success and result.adapter_name == "LocalEventLogAdapter"
    assert result.raw_result.state == result.sanitized_result.state == LocalExecutionState.SUCCESS
    assert "nenhum Event Log" in result.raw_result.stdout


def test_custom_event_adapter_executes_and_sanitizes_same_raw():
    adapter = EventSpy(); result = LocalAdapterDispatcher(event_log_adapter=adapter).dispatch(contract(), 10)
    assert result.success and len(adapter.execute_calls) == len(adapter.sanitize_calls) == 1
    assert adapter.sanitize_calls[0] == result.raw_result


@pytest.mark.parametrize("field,value", [
    ("operation.operation_name", "read_system_information"),
    ("command.operation_name", "read_system_information"),
    ("operation.adapter_type", LocalAdapterType.SYSTEM_INFORMATION),
    ("command.adapter_type", LocalAdapterType.DISK_INFORMATION),
    ("command.target", ExecutionTarget.LINUX),
    ("command.target", ExecutionTarget.REMOTE_AGENT),
    ("command.target", ExecutionTarget.UNKNOWN),
    ("command.risk", ExecutionRisk.MEDIUM),
    ("command.risk", ExecutionRisk.HIGH),
    ("command.risk", ExecutionRisk.CRITICAL),
    ("operation.operation_type", LocalOperationType.STATE_CHANGING),
    ("command.operation_type", LocalOperationType.DESTRUCTIVE),
    ("command.timeout_seconds", 0),
    ("command.timeout_seconds", 31),
    ("command.dry_run", "true"),
])
def test_event_contract_guard_fails_closed(field, value):
    item = contract(); parent, child = field.split(".")
    object.__setattr__(getattr(item, parent), child, value)
    result = LocalAdapterDispatcher().dispatch(item, 10)
    assert not result.success and result.raw_result is None


@pytest.mark.parametrize("field", [
    "allow_shell", "allow_arbitrary_command", "allow_environment_inheritance",
    "allow_network_access", "allow_filesystem_write", "allow_registry_write",
    "allow_service_state_change", "allow_process_termination", "allow_elevation",
    "allow_child_processes",
])
def test_event_unsafe_sandbox_is_blocked_before_adapter(field):
    adapter = EventSpy()
    sandbox = replace(LocalSandboxPolicy(), **{field: True})
    result = LocalAdapterDispatcher(event_log_adapter=adapter).dispatch(contract(sandbox=sandbox), 10)
    assert not result.success and adapter.execute_calls == []


@pytest.mark.parametrize("field", [
    "allow_windows_event_log_adapter", "allow_windows_target", "allow_low_risk",
    "allow_read_only_operations", "allow_dry_run",
])
def test_custom_policy_can_block_event_dry_run(field):
    adapter = EventSpy(); policy = replace(DiagnosticLocalExecutorPolicy(), **{field: False})
    result = LocalAdapterDispatcher(event_log_adapter=adapter, policy=policy).dispatch(contract(), 10)
    assert not result.success and adapter.execute_calls == []


def test_default_policy_blocks_real_event_before_delegation():
    adapter = EventSpy()
    result = LocalAdapterDispatcher(event_log_adapter=adapter).dispatch(contract(dry_run=False), 10)
    assert not result.success and adapter.execute_calls == []


def test_explicit_real_policy_delegates_event_operation():
    adapter = EventSpy()
    policy = replace(DiagnosticLocalExecutorPolicy(), allow_local_execution=True, allow_real_execution=True)
    result = LocalAdapterDispatcher(event_log_adapter=adapter, policy=policy).dispatch(
        contract(dry_run=False), 10,
    )
    assert result.success and len(adapter.execute_calls) == 1


def test_missing_real_backend_failure_is_preserved(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.local_event_log_adapter._event_log_backend", None)
    monkeypatch.setattr("app.services.diagnostic_engine.local_event_log_adapter.platform.system", lambda: "Windows")
    policy = replace(DiagnosticLocalExecutorPolicy(), allow_local_execution=True, allow_real_execution=True)
    result = LocalAdapterDispatcher(policy=policy).dispatch(contract(dry_run=False), 10)
    assert not result.success
    assert result.raw_result.stderr == "Backend seguro de Event Log indisponível."
    assert result.sanitized_result.stderr_summary == result.raw_result.stderr


def test_event_failed_raw_is_preserved_and_sanitized():
    adapter = EventSpy(failure=True)
    result = LocalAdapterDispatcher(event_log_adapter=adapter).dispatch(contract(), 10)
    assert not result.success and result.raw_result.state == LocalExecutionState.FAILED
    assert result.sanitized_result is not None and len(adapter.sanitize_calls) == 1


def test_event_execute_exception_is_generic_without_stack():
    adapter = EventSpy(execute_error=True)
    result = LocalAdapterDispatcher(event_log_adapter=adapter).dispatch(contract(), 10)
    assert not result.success and result.errors == ("Falha no adapter local.",)
    assert result.raw_result is None and "sensitive" not in " ".join(result.errors).lower()


def test_event_sanitizer_exception_preserves_raw():
    adapter = EventSpy(sanitize_error=True)
    result = LocalAdapterDispatcher(event_log_adapter=adapter).dispatch(contract(), 10)
    assert not result.success and result.errors == ("Falha no adapter local.",)
    assert result.raw_result is not None and result.sanitized_result is None


def test_event_mismatched_raw_command_is_blocked():
    result = LocalAdapterDispatcher(event_log_adapter=EventSpy(bad_id=True)).dispatch(contract(), 10)
    assert not result.success and result.raw_result is None


@pytest.mark.parametrize("subject", ["contract", "operation", "command", "sandbox", "arguments"])
def test_event_dispatch_does_not_mutate_contract_graph(subject):
    item = contract(hours=24); selected = {
        "contract": item, "operation": item.operation, "command": item.command,
        "sandbox": item.sandbox_policy, "arguments": item.command.arguments,
    }[subject]
    before = deepcopy(selected); LocalAdapterDispatcher().dispatch(item, 10)
    assert selected == before


def test_event_adapter_and_registry_are_stable_after_dispatch():
    adapter = EventSpy(); dispatcher = LocalAdapterDispatcher(event_log_adapter=adapter)
    before_operations = dispatcher.supported_operations(); before_adapter = dispatcher.resolve("collect_event_logs")
    dispatcher.dispatch(contract(), 10)
    assert dispatcher.supported_operations() == before_operations
    assert dispatcher.resolve("collect_event_logs") is before_adapter


@pytest.mark.parametrize("operation", ["read_system_information", "check_disk_information", "check_disk_space"])
def test_existing_operations_still_dispatch_successfully(operation):
    item = SafeLocalOperationCatalog().build_contract(
        contract_id="contract-1", executor_request_id="executor-1", execution_plan_id="plan-1",
        action_id="action-1", grant_id="grant-1", operation_name=operation,
        command_id="command-1", dry_run=True,
    )
    assert LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("operation", UNSUPPORTED)
def test_unsupported_catalog_operations_never_resolve(operation):
    dispatcher = LocalAdapterDispatcher()
    assert not dispatcher.contains(operation) and dispatcher.resolve(operation) is None


def test_public_imports_remain_available():
    from app.services.diagnostic_engine import LocalAdapterDispatcher as PublicDispatcher
    from app.services.diagnostic_engine import LocalEventLogAdapter as PublicEventAdapter
    assert PublicDispatcher is LocalAdapterDispatcher and PublicEventAdapter is LocalEventLogAdapter


@pytest.mark.parametrize("name", [
    "win32evtlog", "subprocess", "os", "socket", "requests", "urllib", "httpx", "pathlib",
])
def test_dispatcher_has_no_operational_imports(name):
    tree = ast.parse(DISPATCHER_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "openeventlog", "readeventlog", "closeeventlog", "powershell.exe", "cmd.exe",
    "wevtutil", "wmic", "os.system", "subprocess.run", "socket.socket",
    "requests.get", "httpx.get", "open(", "disk_usage", "platform.system",
])
def test_dispatcher_has_no_direct_collection_or_forbidden_calls(text):
    assert text not in DISPATCHER_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("path", [DISPATCHER_FILE, PACKAGE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
