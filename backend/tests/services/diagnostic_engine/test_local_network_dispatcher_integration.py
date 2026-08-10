import ast
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from app.services.diagnostic_engine import (
    LocalAdapterDispatcher, LocalDiskInformationAdapter, LocalEventLogAdapter,
    LocalNetworkDiagnosticAdapter, LocalProcessAdapter, LocalSystemInformationAdapter,
    LocalWindowsServiceAdapter,
)
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalExecutionState, LocalOperationType, LocalOutputChunk,
    LocalRawExecutionResult, LocalSandboxPolicy, LocalSanitizedResult, OutputStreamType,
)
from app.services.diagnostic_engine.local_executor_policy import DiagnosticLocalExecutorPolicy
from app.services.diagnostic_engine.local_operation_catalog import SafeLocalOperationCatalog


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
DISPATCHER_FILE = ROOT / "app/services/diagnostic_engine/local_adapter_dispatcher.py"
PACKAGE_FILE = DISPATCHER_FILE.with_name("__init__.py")
OPERATIONS = (
    "check_disk_information", "check_disk_space", "check_network_configuration",
    "check_service_status", "collect_event_logs", "list_processes",
    "list_windows_services", "read_system_information",
    "read_system_process_information",
)
UNSUPPORTED = (
    "ping_host", "check_port", "validate_configuration", "network", "check_network",
    "PING_HOST", "port_scan", "traceroute", "dns_lookup", "http_check", "unknown",
)


def contract(*, dry_run=True, sandbox=None):
    return SafeLocalOperationCatalog().build_contract(
        contract_id="contract-1", executor_request_id="executor-1",
        execution_plan_id="plan-1", action_id="action-1", grant_id="grant-1",
        operation_name="check_network_configuration", command_id="command-1",
        dry_run=dry_run, sandbox_policy=sandbox,
    )


def raw(state=LocalExecutionState.SUCCESS, command_id="command-1"):
    stdout = '{"operation":"network"}' if state == LocalExecutionState.SUCCESS else ""
    chunks = () if not stdout else (LocalOutputChunk(
        sequence=0, stream=OutputStreamType.STDOUT, content=stdout, truncated=False,
        redacted=False, redaction_reasons=(), occurred_at_monotonic=10,
    ),)
    return LocalRawExecutionResult(
        command_id=command_id, state=state, started_at_monotonic=10,
        finished_at_monotonic=10, exit_code=0 if stdout else None, stdout=stdout,
        stderr="" if stdout else "network failure", output_chunks=chunks,
        timed_out=False, cancelled=False,
        errors=() if stdout else ("network failure",),
    )


class NetworkSpy(LocalNetworkDiagnosticAdapter):
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
            raise RuntimeError("sensitive network stack")
        return raw(
            LocalExecutionState.FAILED if self.failed else LocalExecutionState.SUCCESS,
            "other-command" if self.bad_id else item.command.command_id,
        )

    def sanitize(self, result):
        self.sanitize_calls.append(result)
        if self.sanitize_error:
            raise RuntimeError("sensitive network sanitizer stack")
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


def test_default_constructor_creates_distinct_network_adapters():
    first = LocalAdapterDispatcher(); second = LocalAdapterDispatcher()
    assert isinstance(first.network_diagnostic_adapter, LocalNetworkDiagnosticAdapter)
    assert first.network_diagnostic_adapter is not second.network_diagnostic_adapter


def test_custom_network_adapter_and_policy_are_preserved():
    adapter = NetworkSpy(); policy = DiagnosticLocalExecutorPolicy()
    dispatcher = LocalAdapterDispatcher(network_diagnostic_adapter=adapter, policy=policy)
    assert dispatcher.network_diagnostic_adapter is adapter and dispatcher.policy is policy


def test_old_positional_constructor_order_is_preserved():
    system = LocalSystemInformationAdapter(); disk = LocalDiskInformationAdapter()
    policy = DiagnosticLocalExecutorPolicy(); event = LocalEventLogAdapter()
    service = LocalWindowsServiceAdapter(); process = LocalProcessAdapter()
    dispatcher = LocalAdapterDispatcher(system, disk, policy, event, service, process)
    assert dispatcher.system_information_adapter is system and dispatcher.disk_information_adapter is disk
    assert dispatcher.policy is policy and dispatcher.event_log_adapter is event
    assert dispatcher.windows_service_adapter is service and dispatcher.process_adapter is process
    assert isinstance(dispatcher.network_diagnostic_adapter, LocalNetworkDiagnosticAdapter)


@pytest.mark.parametrize("invalid", [None, object(), "adapter", 1, True])
def test_invalid_network_adapter_is_rejected(invalid):
    with pytest.raises(ValueError, match="network_diagnostic_adapter"):
        LocalAdapterDispatcher(network_diagnostic_adapter=invalid)


def test_registry_is_immutable_sorted_tuple_with_nine_operations():
    dispatcher = LocalAdapterDispatcher()
    assert isinstance(dispatcher._registry, MappingProxyType)
    assert dispatcher.supported_operations() == OPERATIONS
    assert isinstance(dispatcher.supported_operations(), tuple)
    with pytest.raises(TypeError):
        dispatcher._registry["unknown"] = object()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_contains_all_registered_operations(operation):
    assert LocalAdapterDispatcher().contains(operation)


@pytest.mark.parametrize("operation", UNSUPPORTED + (None, 1, ""))
def test_contains_rejects_unsupported_and_inexact_operations(operation):
    assert not LocalAdapterDispatcher().contains(operation)


def test_resolve_routes_network_operation_exactly():
    dispatcher = LocalAdapterDispatcher()
    assert dispatcher.resolve("check_network_configuration") is dispatcher.network_diagnostic_adapter


@pytest.mark.parametrize("operation,field", [
    ("read_system_information", "system_information_adapter"),
    ("check_disk_information", "disk_information_adapter"),
    ("check_disk_space", "disk_information_adapter"),
    ("collect_event_logs", "event_log_adapter"),
    ("list_windows_services", "windows_service_adapter"),
    ("check_service_status", "windows_service_adapter"),
    ("list_processes", "process_adapter"),
    ("read_system_process_information", "process_adapter"),
])
def test_resolve_preserves_existing_routes(operation, field):
    dispatcher = LocalAdapterDispatcher()
    assert dispatcher.resolve(operation) is getattr(dispatcher, field)


@pytest.mark.parametrize("operation", UNSUPPORTED + (None, object(), "network_configuration"))
def test_resolve_has_no_fuzzy_or_fallback_route(operation):
    assert LocalAdapterDispatcher().resolve(operation) is None


def test_default_policy_delegates_network_dry_run_to_same_adapter():
    adapter = NetworkSpy()
    result = LocalAdapterDispatcher(network_diagnostic_adapter=adapter).dispatch(contract(), 10)
    assert result.success and result.adapter_name == "NetworkSpy"
    assert len(adapter.execute_calls) == len(adapter.sanitize_calls) == 1
    assert result.raw_result is not None and result.sanitized_result is not None
    assert adapter.sanitize_calls[0] == result.raw_result


@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("adapter_type", [
    LocalAdapterType.UNKNOWN, LocalAdapterType.SYSTEM_INFORMATION,
    LocalAdapterType.DISK_INFORMATION, LocalAdapterType.PROCESS,
    LocalAdapterType.WINDOWS_EVENT_LOG, LocalAdapterType.WINDOWS_SERVICE,
])
def test_wrong_adapter_type_fails_closed(field, adapter_type):
    item = contract(); object.__setattr__(getattr(item, field), "adapter_type", adapter_type)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("target", [
    ExecutionTarget.WINDOWS, ExecutionTarget.LOCAL_MACHINE, ExecutionTarget.LINUX,
    ExecutionTarget.REMOTE_AGENT, ExecutionTarget.UNKNOWN,
])
def test_wrong_target_fails_closed(target):
    item = contract(); object.__setattr__(item.command, "target", target)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("risk", [ExecutionRisk.MEDIUM, ExecutionRisk.HIGH, ExecutionRisk.CRITICAL])
def test_wrong_risk_fails_closed(risk):
    item = contract(); object.__setattr__(item.command, "risk", risk)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("kind", [LocalOperationType.STATE_CHANGING, LocalOperationType.DESTRUCTIVE])
def test_mutable_operation_types_fail_closed(field, kind):
    item = contract(); object.__setattr__(getattr(item, field), "operation_type", kind)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("timeout", [0, -1, 31, 61, True, "30", None])
def test_invalid_timeout_fails_closed(timeout):
    item = contract(); object.__setattr__(item.command, "timeout_seconds", timeout)
    assert not LocalAdapterDispatcher().dispatch(item, 10).success


@pytest.mark.parametrize("state", [
    LocalExecutionState.BLOCKED, LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS,
    LocalExecutionState.FAILED, LocalExecutionState.CANCELLED, LocalExecutionState.TIMED_OUT,
])
def test_invalid_states_fail_closed(state):
    item = contract(); object.__setattr__(item, "state", state)
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
    "allow_network_diagnostic_adapter", "allow_network_target", "allow_low_risk",
    "allow_read_only_operations", "allow_dry_run",
])
def test_policy_can_block_each_structural_gate(field):
    policy = replace(DiagnosticLocalExecutorPolicy(), **{field: False})
    adapter = NetworkSpy()
    result = LocalAdapterDispatcher(
        network_diagnostic_adapter=adapter, policy=policy
    ).dispatch(contract(), 10)
    assert not result.success and not adapter.execute_calls


def test_default_policy_blocks_real_execution_before_adapter():
    adapter = NetworkSpy()
    result = LocalAdapterDispatcher(network_diagnostic_adapter=adapter).dispatch(
        contract(dry_run=False), 10
    )
    assert not result.success and not adapter.execute_calls


def test_custom_real_policy_delegates_to_network_adapter():
    adapter = NetworkSpy()
    result = LocalAdapterDispatcher(
        network_diagnostic_adapter=adapter, policy=real_policy()
    ).dispatch(contract(dry_run=False), 10)
    assert result.success and len(adapter.execute_calls) == 1


def test_missing_backend_message_is_preserved_without_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_network_diagnostic_adapter._network_backend", None
    )
    result = LocalAdapterDispatcher(policy=real_policy()).dispatch(contract(dry_run=False), 10)
    assert not result.success and result.raw_result is not None
    assert result.raw_result.stderr == "Backend seguro de configuração de rede indisponível."


@pytest.mark.parametrize("mode", ["failed", "execute_error", "sanitize_error", "bad_id"])
def test_adapter_and_sanitizer_failures_are_generic(mode):
    adapter = NetworkSpy(**{mode: True})
    result = LocalAdapterDispatcher(network_diagnostic_adapter=adapter).dispatch(contract(), 10)
    assert not result.success and "sensitive" not in " ".join(result.errors).lower()
    if mode == "sanitize_error":
        assert result.raw_result is not None and result.sanitized_result is None


@pytest.mark.parametrize("subject", ["contract", "operation", "command", "sandbox"])
def test_dispatch_preserves_contract_graph(subject):
    item = contract(); selected = {
        "contract": item, "operation": item.operation, "command": item.command,
        "sandbox": item.sandbox_policy,
    }[subject]
    before = deepcopy(selected); LocalAdapterDispatcher().dispatch(item, 10)
    assert selected == before


def test_dispatch_preserves_registry_and_adapter_identity():
    adapter = NetworkSpy(); dispatcher = LocalAdapterDispatcher(network_diagnostic_adapter=adapter)
    before = dispatcher.supported_operations(); dispatcher.dispatch(contract(), 10)
    assert dispatcher.supported_operations() == before
    assert dispatcher.resolve("check_network_configuration") is adapter


@pytest.mark.parametrize("name", [
    "psutil", "socket", "subprocess", "requests", "httpx", "urllib", "aiohttp",
])
def test_dispatcher_has_no_forbidden_operational_import(name):
    tree = ast.parse(DISPATCHER_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "net_if_addrs", "net_if_stats", "net_connections", "socket.", ".connect(",
    ".send(", ".sendto(", "requests.", "httpx.", "urllib.", "aiohttp.",
    "subprocess", "os.system", "powershell", "cmd.exe", "ipconfig", "netsh",
    "wmic", "ping_host", "check_port", "tracert", "traceroute", "nslookup",
    "dns_lookup", "port_scan",
])
def test_dispatcher_has_no_network_backend_probe_shell_or_fallback(text):
    assert text not in DISPATCHER_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("path", [DISPATCHER_FILE, PACKAGE_FILE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes()
    assert not content.startswith(b"\xef\xbb\xbf")
    content.decode("utf-8")
