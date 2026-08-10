import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import MappingProxyType

import pytest

from app.services.diagnostic_engine import (
    LocalAdapterDispatcher,
    LocalAdapterDispatchResult,
    LocalDiskInformationAdapter,
    LocalSystemInformationAdapter,
)
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalExecutionContract, LocalExecutionState, LocalOperationType,
    LocalOutputChunk, LocalRawExecutionResult, LocalSandboxPolicy, LocalSanitizedResult,
    OutputStreamType,
)
from app.services.diagnostic_engine.local_executor_policy import DiagnosticLocalExecutorPolicy
from app.services.diagnostic_engine.local_operation_catalog import SafeLocalOperationCatalog


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
DISPATCHER_FILE = ROOT / "app/services/diagnostic_engine/local_adapter_dispatcher.py"
PACKAGE = DISPATCHER_FILE.with_name("__init__.py")
OPERATIONS = ("check_disk_information", "check_disk_space", "read_system_information")
SUPPORTED_OPERATIONS = (
    "check_disk_information", "check_disk_space", "check_network_configuration", "check_service_status",
    "collect_event_logs", "list_processes", "list_windows_services",
    "read_system_information", "read_system_process_information",
)


def contract(operation="read_system_information", *, dry_run=True, sandbox=None):
    return SafeLocalOperationCatalog().build_contract(
        contract_id="contract-1", executor_request_id="executor-1", execution_plan_id="plan-1",
        action_id="action-1", grant_id="grant-1", operation_name=operation,
        command_id="command-1", dry_run=dry_run, sandbox_policy=sandbox,
    )


def raw(state=LocalExecutionState.SUCCESS, command_id="command-1"):
    message = "ok"
    chunk = LocalOutputChunk(
        sequence=0, stream=OutputStreamType.STDOUT, content=message, truncated=False,
        redacted=False, redaction_reasons=(), occurred_at_monotonic=10,
    )
    return LocalRawExecutionResult(
        command_id=command_id, state=state, started_at_monotonic=10,
        finished_at_monotonic=10, exit_code=0 if state == LocalExecutionState.SUCCESS else None,
        stdout=message if state == LocalExecutionState.SUCCESS else "",
        stderr="" if state == LocalExecutionState.SUCCESS else "generic failure",
        output_chunks=(chunk,) if state == LocalExecutionState.SUCCESS else (),
        timed_out=False, cancelled=False,
    )


class SystemSpy(LocalSystemInformationAdapter):
    def __init__(self, *, failure=False, raises=False, bad_sanitize=False):
        self.execute_calls = []
        self.sanitize_calls = []
        self.failure = failure
        self.raises = raises
        self.bad_sanitize = bad_sanitize

    def execute(self, item, now):
        self.execute_calls.append((item, now))
        if self.raises:
            raise RuntimeError("sensitive stack")
        return raw(LocalExecutionState.FAILED if self.failure else LocalExecutionState.SUCCESS)

    def sanitize(self, result):
        self.sanitize_calls.append(result)
        if self.bad_sanitize:
            raise RuntimeError("sensitive sanitizer stack")
        return LocalSanitizedResult(
            command_id=result.command_id, state=result.state, exit_code=result.exit_code,
            stdout_summary=result.stdout, stderr_summary=result.stderr, redactions=(),
            truncated=False, output_bytes=len(result.stdout.encode()) + len(result.stderr.encode()),
            errors=result.errors,
        )


class DiskSpy(LocalDiskInformationAdapter):
    def __init__(self):
        self.execute_calls = []
        self.sanitize_calls = []

    def execute(self, item, now):
        self.execute_calls.append((item, now)); return raw()

    def sanitize(self, result):
        self.sanitize_calls.append(result)
        return LocalSanitizedResult(
            command_id=result.command_id, state=result.state, exit_code=result.exit_code,
            stdout_summary=result.stdout, stderr_summary=result.stderr, redactions=(),
            truncated=False, output_bytes=len(result.stdout.encode()),
        )


def test_default_constructor_creates_distinct_adapters_and_policy():
    first = LocalAdapterDispatcher(); second = LocalAdapterDispatcher()
    assert isinstance(first.system_information_adapter, LocalSystemInformationAdapter)
    assert isinstance(first.disk_information_adapter, LocalDiskInformationAdapter)
    assert isinstance(first.policy, DiagnosticLocalExecutorPolicy)
    assert first.system_information_adapter is not second.system_information_adapter


def test_custom_constructor_dependencies_are_preserved():
    system = SystemSpy(); disk = DiskSpy(); policy = DiagnosticLocalExecutorPolicy()
    dispatcher = LocalAdapterDispatcher(system, disk, policy)
    assert dispatcher.system_information_adapter is system
    assert dispatcher.disk_information_adapter is disk and dispatcher.policy is policy


@pytest.mark.parametrize("field,value", [
    ("system_information_adapter", object()), ("disk_information_adapter", object()),
    ("policy", object()), ("system_information_adapter", None),
    ("disk_information_adapter", None), ("policy", None),
])
def test_constructor_rejects_invalid_dependency(field, value):
    with pytest.raises(ValueError, match=field):
        LocalAdapterDispatcher(**{field: value})


def test_registry_is_private_mapping_proxy():
    dispatcher = LocalAdapterDispatcher()
    assert isinstance(dispatcher._registry, MappingProxyType)
    with pytest.raises(TypeError): dispatcher._registry["unknown"] = object()


def test_supported_operations_are_sorted_deterministic_tuple():
    dispatcher = LocalAdapterDispatcher()
    assert dispatcher.supported_operations() == SUPPORTED_OPERATIONS
    assert isinstance(dispatcher.supported_operations(), tuple)
    assert dispatcher.supported_operations() == dispatcher.supported_operations()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_contains_registered_operation(operation):
    assert LocalAdapterDispatcher().contains(operation)


@pytest.mark.parametrize("unknown", [None, 1, "", "unknown", "read", "disk", "READ_SYSTEM_INFORMATION"])
def test_contains_unknown_is_false(unknown):
    assert not LocalAdapterDispatcher().contains(unknown)


def test_resolve_routes_system_adapter():
    dispatcher = LocalAdapterDispatcher()
    assert dispatcher.resolve("read_system_information") is dispatcher.system_information_adapter


@pytest.mark.parametrize("operation", ["check_disk_information", "check_disk_space"])
def test_resolve_routes_disk_adapter(operation):
    dispatcher = LocalAdapterDispatcher()
    assert dispatcher.resolve(operation) is dispatcher.disk_information_adapter


@pytest.mark.parametrize("unknown", [None, object(), "", "check_disk", "read_system"])
def test_resolve_unknown_has_no_fallback(unknown):
    assert LocalAdapterDispatcher().resolve(unknown) is None


@pytest.mark.parametrize("operation,expected", [
    ("read_system_information", "LocalSystemInformationAdapter"),
    ("check_disk_information", "LocalDiskInformationAdapter"),
    ("check_disk_space", "LocalDiskInformationAdapter"),
])
def test_default_dry_run_dispatches_and_sanitizes(operation, expected):
    result = LocalAdapterDispatcher().dispatch(contract(operation), 10)
    assert result.success and result.adapter_name == expected
    assert isinstance(result.raw_result, LocalRawExecutionResult)
    assert isinstance(result.sanitized_result, LocalSanitizedResult)
    assert result.raw_result.command_id == result.sanitized_result.command_id == "command-1"


def test_system_dispatch_uses_same_adapter_for_execute_and_sanitize():
    system = SystemSpy(); disk = DiskSpy()
    result = LocalAdapterDispatcher(system, disk).dispatch(contract(), 10)
    assert result.success and len(system.execute_calls) == len(system.sanitize_calls) == 1
    assert not disk.execute_calls and system.sanitize_calls[0] is not result.raw_result
    assert system.sanitize_calls[0] == result.raw_result


@pytest.mark.parametrize("operation", ["check_disk_information", "check_disk_space"])
def test_disk_dispatch_uses_same_adapter_for_execute_and_sanitize(operation):
    system = SystemSpy(); disk = DiskSpy()
    result = LocalAdapterDispatcher(system, disk).dispatch(contract(operation), 10)
    assert result.success and len(disk.execute_calls) == len(disk.sanitize_calls) == 1
    assert not system.execute_calls and disk.sanitize_calls[0] == result.raw_result


@pytest.mark.parametrize("invalid", [None, object(), "contract", 1])
def test_invalid_contract_fails_closed(invalid):
    result = LocalAdapterDispatcher().dispatch(invalid, 10)
    assert not result.success and result.contract is None and result.raw_result is None


@pytest.mark.parametrize("field,value", [
    ("operation.operation_name", "ping_host"),
    ("command.operation_name", "ping_host"),
    ("operation.operation_name", "read_system"),
    ("command.operation_name", "check_disk"),
])
def test_unknown_or_mismatched_operation_is_blocked(field, value):
    item = contract(); parent, child = field.split(".")
    object.__setattr__(getattr(item, parent), child, value)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("adapter", [LocalAdapterType.UNKNOWN, LocalAdapterType.PROCESS])
def test_wrong_adapter_is_blocked(operation, field, adapter):
    item = contract(operation); object.__setattr__(getattr(item, field), "adapter_type", adapter)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("target", [
    ExecutionTarget.LOCAL_MACHINE, ExecutionTarget.LINUX, ExecutionTarget.NETWORK,
    ExecutionTarget.REMOTE_AGENT, ExecutionTarget.UNKNOWN,
])
def test_wrong_target_is_blocked(target):
    item = contract(); object.__setattr__(item.command, "target", target)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("risk", [ExecutionRisk.MEDIUM, ExecutionRisk.HIGH, ExecutionRisk.CRITICAL])
def test_wrong_risk_is_blocked(risk):
    item = contract(); object.__setattr__(item.command, "risk", risk)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("kind", [LocalOperationType.STATE_CHANGING, LocalOperationType.DESTRUCTIVE])
@pytest.mark.parametrize("field", ["operation", "command"])
def test_wrong_operation_type_is_blocked(kind, field):
    item = contract(); object.__setattr__(getattr(item, field), "operation_type", kind)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("state", [
    LocalExecutionState.BLOCKED, LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS,
    LocalExecutionState.FAILED, LocalExecutionState.CANCELLED, LocalExecutionState.TIMED_OUT,
])
def test_wrong_contract_state_is_blocked(state):
    item = contract(); object.__setattr__(item, "state", state)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("timeout", [0, -1, 31, 61, True, "30"])
def test_invalid_timeout_is_blocked(timeout):
    item = contract(); object.__setattr__(item.command, "timeout_seconds", timeout)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("field_name", [
    "allow_shell", "allow_arbitrary_command", "allow_environment_inheritance",
    "allow_network_access", "allow_filesystem_write", "allow_registry_write",
    "allow_service_state_change", "allow_process_termination", "allow_elevation",
    "allow_child_processes",
])
def test_unsafe_sandbox_is_blocked(field_name):
    item = contract(sandbox=replace(LocalSandboxPolicy(), **{field_name: True}))
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("invalid", [-1, True, "10", None])
def test_invalid_monotonic_time_is_blocked(invalid):
    assert not LocalAdapterDispatcher().dispatch(contract(), invalid).success


@pytest.mark.parametrize("field", [
    "allow_system_information_adapter", "allow_windows_target", "allow_low_risk",
    "allow_read_only_operations", "allow_dry_run",
])
def test_policy_can_block_dry_run(field):
    dispatcher = LocalAdapterDispatcher(policy=replace(DiagnosticLocalExecutorPolicy(), **{field: False}))
    assert not dispatcher.dispatch(contract(), 10).success


@pytest.mark.parametrize("field", ["allow_disk_information_adapter", "allow_windows_target", "allow_low_risk"])
def test_policy_can_block_disk_dry_run(field):
    policy = replace(DiagnosticLocalExecutorPolicy(), **{field: False})
    assert not LocalAdapterDispatcher(policy=policy).dispatch(contract("check_disk_space"), 10).success


def test_default_policy_blocks_real_execution_before_adapter_call():
    system = SystemSpy()
    result = LocalAdapterDispatcher(system_information_adapter=system).dispatch(contract(dry_run=False), 10)
    assert not result.success and not system.execute_calls


def test_explicit_policy_can_allow_structural_real_delegation():
    system = SystemSpy()
    policy = replace(DiagnosticLocalExecutorPolicy(), allow_local_execution=True, allow_real_execution=True)
    result = LocalAdapterDispatcher(system_information_adapter=system, policy=policy).dispatch(
        contract(dry_run=False), 10
    )
    assert result.success and len(system.execute_calls) == 1


@pytest.mark.parametrize("operation", OPERATIONS)
def test_only_registered_real_operation_can_be_delegated(operation):
    system = SystemSpy(); disk = DiskSpy()
    policy = replace(DiagnosticLocalExecutorPolicy(), allow_local_execution=True, allow_real_execution=True)
    result = LocalAdapterDispatcher(system, disk, policy).dispatch(contract(operation, dry_run=False), 10)
    assert result.success


def test_adapter_failed_result_becomes_dispatch_failure_but_is_sanitized():
    system = SystemSpy(failure=True)
    result = LocalAdapterDispatcher(system_information_adapter=system).dispatch(contract(), 10)
    assert not result.success and result.raw_result.state == LocalExecutionState.FAILED
    assert result.sanitized_result is not None and len(system.sanitize_calls) == 1


def test_adapter_exception_is_generic_and_has_no_stack_detail():
    result = LocalAdapterDispatcher(system_information_adapter=SystemSpy(raises=True)).dispatch(contract(), 10)
    assert not result.success and result.errors == ("Falha no adapter local.",)
    assert "sensitive" not in " ".join(result.errors).lower()


def test_sanitizer_exception_is_generic():
    result = LocalAdapterDispatcher(system_information_adapter=SystemSpy(bad_sanitize=True)).dispatch(contract(), 10)
    assert not result.success and result.errors == ("Falha no adapter local.",)
    assert result.raw_result is not None and result.sanitized_result is None


@pytest.mark.parametrize("invalid", [None, 0, 1, "true"])
def test_non_boolean_dry_run_is_blocked(invalid):
    item = contract(); object.__setattr__(item.command, "dry_run", invalid)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("subject", ["contract", "operation", "command", "sandbox"])
def test_dispatch_does_not_mutate_contract_graph(subject):
    item = contract(); selected = {
        "contract": item, "operation": item.operation, "command": item.command,
        "sandbox": item.sandbox_policy,
    }[subject]
    before = deepcopy(selected); LocalAdapterDispatcher().dispatch(item, 10)
    assert selected == before


def test_result_is_frozen_and_defensively_copies_metadata():
    metadata = {"safe": ["value"]}
    result = LocalAdapterDispatchResult(metadata=metadata)
    metadata["safe"].append("changed")
    assert result.metadata == {"safe": ["value"]}
    with pytest.raises(FrozenInstanceError): result.success = True


@pytest.mark.parametrize("metadata", [
    {"password": "x"}, {"token": "x"}, {"safe": "credential"}, {"authorization": "x"},
])
def test_result_rejects_sensitive_metadata(metadata):
    with pytest.raises(ValueError, match="sensitive"):
        LocalAdapterDispatchResult(metadata=metadata)


def test_result_enforces_matching_command_ids():
    with pytest.raises(ValueError, match="command_id"):
        LocalAdapterDispatchResult(contract=contract(), raw_result=raw(command_id="other"))


def test_success_result_requires_complete_snapshots():
    with pytest.raises(ValueError, match="requires"):
        LocalAdapterDispatchResult(success=True, contract=contract())


@pytest.mark.parametrize("operation", OPERATIONS)
def test_routing_is_deterministic(operation):
    dispatcher = LocalAdapterDispatcher()
    assert dispatcher.resolve(operation) is dispatcher.resolve(operation)
    assert dispatcher.dispatch(contract(operation), 10) == dispatcher.dispatch(contract(operation), 10)


def test_public_imports():
    from app.services.diagnostic_engine import LocalAdapterDispatcher as PublicDispatcher
    from app.services.diagnostic_engine import LocalAdapterDispatchResult as PublicResult
    assert PublicDispatcher is LocalAdapterDispatcher and PublicResult is LocalAdapterDispatchResult


@pytest.mark.parametrize("name", [
    "subprocess", "os", "socket", "requests", "httpx", "pathlib", "importlib", "glob",
])
def test_dispatcher_has_no_forbidden_imports(name):
    tree = ast.parse(DISPATCHER_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "powershell.exe", "cmd.exe", "wmic", "shell=true", "os.system", "subprocess.run",
    "socket.socket", "requests.get", "httpx.get", "open(", "pathlib.path", "consume_grant",
    "session_engine", "disk_usage", "platform.system",
])
def test_dispatcher_has_no_forbidden_invocations(text):
    assert text not in DISPATCHER_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("path", [DISPATCHER_FILE, PACKAGE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
