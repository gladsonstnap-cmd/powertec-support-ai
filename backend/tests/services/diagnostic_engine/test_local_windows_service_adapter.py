import ast
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import LocalWindowsServiceAdapter
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalExecutionState, LocalOperationArgument, LocalOperationType,
    LocalRawExecutionResult, LocalSandboxPolicy, LocalSanitizedResult, RedactionReason,
)
from app.services.diagnostic_engine.local_operation_catalog import SafeLocalOperationCatalog


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ADAPTER_FILE = ROOT / "app/services/diagnostic_engine/local_windows_service_adapter.py"
PACKAGE = ADAPTER_FILE.with_name("__init__.py")


def contract(operation="list_windows_services", *, value=None, dry_run=True, sandbox=None, timeout=30):
    name = "name_filter" if operation == "list_windows_services" else "service_name"
    arguments = () if value is None else (LocalOperationArgument(name, value),)
    return SafeLocalOperationCatalog().build_contract(
        contract_id="contract-1", executor_request_id="executor-1", execution_plan_id="plan-1",
        action_id="action-1", grant_id="grant-1", operation_name=operation,
        command_id="command-1", arguments=arguments, dry_run=dry_run,
        timeout_seconds=timeout, sandbox_policy=sandbox,
    )


class ServiceMissingError(Exception):
    winerror = 1060


class FakeBackend:
    SC_MANAGER_ENUMERATE_SERVICE = 4
    SC_MANAGER_CONNECT = 1
    SERVICE_WIN32 = 48
    SERVICE_STATE_ALL = 3
    SERVICE_QUERY_STATUS = 4
    SERVICE_QUERY_CONFIG = 1

    def __init__(
        self, records=None, *, state=4, start_type=2, display_name="Test Service",
        manager_error=False, enum_error=False, open_error=False, missing=False,
        query_status_error=False, query_config_error=False, close_error=False,
    ):
        self.records = records if records is not None else [
            ("TestSvc", "Test Service", {"CurrentState": 4}),
        ]
        self.state = state
        self.start_type = start_type
        self.display_name = display_name
        self.manager_error = manager_error
        self.enum_error = enum_error
        self.open_error = open_error
        self.missing = missing
        self.query_status_error = query_status_error
        self.query_config_error = query_config_error
        self.close_error = close_error
        self.manager_calls = []
        self.enum_calls = []
        self.open_calls = []
        self.status_calls = []
        self.config_calls = []
        self.close_calls = []

    def OpenSCManager(self, machine, database, access):
        self.manager_calls.append((machine, database, access))
        if self.manager_error:
            raise RuntimeError(r"sensitive C:\\Users\\Private")
        return "MANAGER"

    def EnumServicesStatus(self, manager, service_type, state):
        self.enum_calls.append((manager, service_type, state))
        if self.enum_error:
            raise RuntimeError("sensitive enum stack")
        return self.records

    def OpenService(self, manager, service_name, access):
        self.open_calls.append((manager, service_name, access))
        if self.missing:
            raise ServiceMissingError()
        if self.open_error:
            raise RuntimeError("sensitive open stack")
        return "SERVICE"

    def QueryServiceStatus(self, service):
        self.status_calls.append(service)
        if self.query_status_error:
            raise RuntimeError("sensitive status stack")
        return (0, self.state, 0, 0, 0, 0, 0)

    def QueryServiceConfig(self, service):
        self.config_calls.append(service)
        if self.query_config_error:
            raise RuntimeError("sensitive config stack")
        return (0, self.start_type, 0, r"C:\\Private\\service.exe", "", 0, (), "PRIVATE\\account", self.display_name)

    def CloseServiceHandle(self, handle):
        self.close_calls.append(handle)
        if self.close_error:
            raise RuntimeError("sensitive close stack")


def real(monkeypatch, operation="list_windows_services", *, value=None, backend=None, sandbox=None):
    selected = backend or FakeBackend()
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_windows_service_adapter._service_backend", selected,
    )
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_windows_service_adapter.platform.system", lambda: "Windows",
    )
    result = LocalWindowsServiceAdapter().execute(
        contract(operation, value=value, dry_run=False, sandbox=sandbox), 10,
    )
    return result, selected


def test_constructor_is_frozen_and_has_public_api():
    adapter = LocalWindowsServiceAdapter()
    assert callable(adapter.execute) and callable(adapter.sanitize)
    assert adapter.operation_names == {"list_windows_services", "check_service_status"}
    with pytest.raises(FrozenInstanceError): adapter.state = "changed"


@pytest.mark.parametrize("operation,value", [
    ("list_windows_services", None), ("list_windows_services", "Test"),
    ("check_service_status", "TestSvc"),
])
def test_valid_dry_run_contract(operation, value):
    result = LocalWindowsServiceAdapter().execute(contract(operation, value=value), 10)
    assert result.state == LocalExecutionState.SUCCESS and result.exit_code == 0


@pytest.mark.parametrize("invalid", [None, object(), "contract", 1])
def test_invalid_contract_fails_closed(invalid):
    result = LocalWindowsServiceAdapter().execute(invalid, 10)
    assert result.state == LocalExecutionState.FAILED and result.exit_code is None


@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("name", ["collect_event_logs", "read_system_information", "start_service", "unknown"])
def test_wrong_operation_is_rejected(field, name):
    item = contract(); object.__setattr__(getattr(item, field), "operation_name", name)
    assert LocalWindowsServiceAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("adapter", [
    LocalAdapterType.WINDOWS_EVENT_LOG, LocalAdapterType.SYSTEM_INFORMATION,
    LocalAdapterType.PROCESS, LocalAdapterType.NETWORK_DIAGNOSTIC,
    LocalAdapterType.DISK_INFORMATION, LocalAdapterType.FILE_INFORMATION, LocalAdapterType.UNKNOWN,
])
def test_wrong_adapter_is_rejected(field, adapter):
    item = contract(); object.__setattr__(getattr(item, field), "adapter_type", adapter)
    assert LocalWindowsServiceAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("target", [
    ExecutionTarget.LOCAL_MACHINE, ExecutionTarget.NETWORK, ExecutionTarget.LINUX,
    ExecutionTarget.REMOTE_AGENT, ExecutionTarget.UNKNOWN,
])
def test_wrong_target_is_rejected(target):
    item = contract(); object.__setattr__(item.command, "target", target)
    assert LocalWindowsServiceAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("risk", [ExecutionRisk.MEDIUM, ExecutionRisk.HIGH, ExecutionRisk.CRITICAL])
def test_wrong_risk_is_rejected(risk):
    item = contract(); object.__setattr__(item.command, "risk", risk)
    assert LocalWindowsServiceAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("kind", [LocalOperationType.STATE_CHANGING, LocalOperationType.DESTRUCTIVE])
def test_wrong_operation_type_is_rejected(field, kind):
    item = contract(); object.__setattr__(getattr(item, field), "operation_type", kind)
    assert LocalWindowsServiceAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("state", [
    LocalExecutionState.BLOCKED, LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS,
    LocalExecutionState.FAILED, LocalExecutionState.CANCELLED, LocalExecutionState.TIMED_OUT,
])
def test_unsafe_contract_state_is_rejected(state):
    item = contract(); object.__setattr__(item, "state", state)
    assert LocalWindowsServiceAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("state", [LocalExecutionState.PENDING, LocalExecutionState.VALIDATED, LocalExecutionState.READY])
def test_initial_contract_states_are_accepted(state):
    item = contract(); object.__setattr__(item, "state", state)
    assert LocalWindowsServiceAdapter().execute(item, 10).state == LocalExecutionState.SUCCESS


@pytest.mark.parametrize("operation,value", [
    ("list_windows_services", "Service"), ("list_windows_services", "Windows Update"),
    ("check_service_status", "wuauserv"), ("check_service_status", "Service.Name_1"),
])
def test_valid_service_identifiers_are_accepted(operation, value):
    assert LocalWindowsServiceAdapter().execute(contract(operation, value=value), 10).state == LocalExecutionState.SUCCESS


@pytest.mark.parametrize("value", [
    "", " ", " Service", "Service ", "*", "?", "[svc]", "svc;", "svc|", "svc&",
    "svc`", "svc$", "svc>", "svc<", "../svc", "svc/path", "svc\\path", "x" * 129,
])
@pytest.mark.parametrize("operation", ["list_windows_services", "check_service_status"])
def test_invalid_service_identifier_is_rejected(operation, value):
    result = LocalWindowsServiceAdapter().execute(contract(operation, value=value), 10)
    assert result.state == LocalExecutionState.FAILED


def test_missing_required_service_name_is_rejected():
    item = contract("check_service_status", value="TestSvc")
    object.__setattr__(item.command, "arguments", ())
    assert LocalWindowsServiceAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("operation,wrong_name", [
    ("list_windows_services", "service_name"), ("check_service_status", "name_filter"),
])
def test_wrong_argument_name_is_rejected(operation, wrong_name):
    item = contract(operation, value="TestSvc")
    object.__setattr__(item.command, "arguments", (LocalOperationArgument(wrong_name, "TestSvc"),))
    assert LocalWindowsServiceAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("timeout", [0, -1, 31, True, "30"])
def test_invalid_timeout_is_rejected(timeout):
    item = contract(); object.__setattr__(item.command, "timeout_seconds", timeout)
    assert LocalWindowsServiceAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field", [
    "allow_shell", "allow_arbitrary_command", "allow_environment_inheritance",
    "allow_network_access", "allow_filesystem_write", "allow_registry_write",
    "allow_service_state_change", "allow_process_termination", "allow_elevation",
    "allow_child_processes",
])
def test_unsafe_sandbox_is_rejected(field):
    sandbox = replace(LocalSandboxPolicy(), **{field: True})
    assert LocalWindowsServiceAdapter().execute(contract(sandbox=sandbox), 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("invalid", [-1, True, "10", None])
def test_invalid_monotonic_time_is_controlled(invalid):
    result = LocalWindowsServiceAdapter().execute(contract(), invalid)
    assert result.state == LocalExecutionState.FAILED and result.started_at_monotonic is None


@pytest.mark.parametrize("operation,value", [
    ("list_windows_services", None), ("check_service_status", "TestSvc"),
])
def test_dry_run_never_calls_backend(monkeypatch, operation, value):
    backend = FakeBackend(manager_error=True)
    monkeypatch.setattr("app.services.diagnostic_engine.local_windows_service_adapter._service_backend", backend)
    result = LocalWindowsServiceAdapter().execute(contract(operation, value=value), 10)
    assert result.state == LocalExecutionState.SUCCESS
    assert backend.manager_calls == backend.enum_calls == backend.open_calls == []


@pytest.mark.parametrize("operation,value", [
    ("list_windows_services", None), ("check_service_status", "TestSvc"),
])
def test_dry_run_exact_message_and_shape(operation, value):
    result = LocalWindowsServiceAdapter().execute(contract(operation, value=value), 10)
    assert result.stdout == "Dry-run: operação de serviços validada; nenhuma consulta real foi realizada."
    assert result.command_id == "command-1" and result.stderr == "" and result.errors == ()
    assert result.started_at_monotonic == result.finished_at_monotonic == 10
    assert len(result.output_chunks) == 1 and result.output_chunks[0].content == result.stdout


def test_non_windows_real_execution_fails_before_backend(monkeypatch):
    backend = FakeBackend(); monkeypatch.setattr("app.services.diagnostic_engine.local_windows_service_adapter._service_backend", backend)
    monkeypatch.setattr("app.services.diagnostic_engine.local_windows_service_adapter.platform.system", lambda: "Linux")
    result = LocalWindowsServiceAdapter().execute(contract(dry_run=False), 10)
    assert result.state == LocalExecutionState.FAILED and backend.manager_calls == []


@pytest.mark.parametrize("operation,value", [
    ("list_windows_services", None), ("check_service_status", "TestSvc"),
])
def test_missing_backend_fails_closed(monkeypatch, operation, value):
    monkeypatch.setattr("app.services.diagnostic_engine.local_windows_service_adapter._service_backend", None)
    monkeypatch.setattr("app.services.diagnostic_engine.local_windows_service_adapter.platform.system", lambda: "Windows")
    result = LocalWindowsServiceAdapter().execute(contract(operation, value=value, dry_run=False), 10)
    assert result.stderr == "Backend seguro de serviços do Windows indisponível."


def test_real_list_empty(monkeypatch):
    result, backend = real(monkeypatch, backend=FakeBackend(records=[]))
    assert json.loads(result.stdout) == {"operation": "list_windows_services", "service_count": 0, "services": []}
    assert backend.close_calls == ["MANAGER"]


def test_real_list_is_sorted_and_structured(monkeypatch):
    records = [
        ("Zulu", "Zulu Service", {"CurrentState": 1}),
        ("alpha", "Alpha Service", {"CurrentState": 4}),
    ]
    result, backend = real(monkeypatch, backend=FakeBackend(records=records))
    data = json.loads(result.stdout)
    assert [item["service_name"] for item in data["services"]] == ["alpha", "Zulu"]
    assert data["services"][0] == {
        "display_name": "Alpha Service", "service_name": "alpha",
        "startup_type": "unknown", "status": "running",
    }
    assert backend.enum_calls == [("MANAGER", 48, 3)]


@pytest.mark.parametrize("filter_value,expected", [
    ("test", ["MyTestSvc", "TestSvc"]), ("TESTSVC", ["MyTestSvc", "TestSvc"]),
    ("missing", []),
])
def test_list_name_filter_is_case_insensitive_substring(monkeypatch, filter_value, expected):
    records = [
        ("TestSvc", "Test", {"CurrentState": 4}),
        ("MyTestSvc", "My Test", {"CurrentState": 1}),
        ("Other", "Other", {"CurrentState": 4}),
    ]
    result, _ = real(monkeypatch, value=filter_value, backend=FakeBackend(records=records))
    assert [item["service_name"] for item in json.loads(result.stdout)["services"]] == expected


def test_list_stops_at_max_services(monkeypatch):
    records = [(f"Svc{index:03}", f"Service {index}", {"CurrentState": 4}) for index in range(250)]
    result, _ = real(monkeypatch, backend=FakeBackend(records=records))
    assert json.loads(result.stdout)["service_count"] == LocalWindowsServiceAdapter.MAX_SERVICES


@pytest.mark.parametrize("state,expected", [
    (1, "stopped"), (2, "start_pending"), (3, "stop_pending"), (4, "running"),
    (5, "continue_pending"), (6, "pause_pending"), (7, "paused"),
    (0, "unknown"), (999, "unknown"),
])
def test_status_normalization(monkeypatch, state, expected):
    result, _ = real(monkeypatch, "check_service_status", value="TestSvc", backend=FakeBackend(state=state))
    assert json.loads(result.stdout)["service"]["status"] == expected


@pytest.mark.parametrize("start_type,expected", [
    (2, "automatic"), (3, "manual"), (4, "disabled"), (0, "unknown"), (999, "unknown"),
])
def test_startup_type_normalization(monkeypatch, start_type, expected):
    result, _ = real(
        monkeypatch, "check_service_status", value="TestSvc",
        backend=FakeBackend(start_type=start_type),
    )
    assert json.loads(result.stdout)["service"]["startup_type"] == expected


def test_check_service_uses_exact_name_and_closes_both_handles(monkeypatch):
    result, backend = real(monkeypatch, "check_service_status", value="Exact.Name")
    assert result.state == LocalExecutionState.SUCCESS
    assert backend.open_calls == [("MANAGER", "Exact.Name", 5)]
    assert backend.close_calls == ["SERVICE", "MANAGER"]


def test_missing_service_has_specific_safe_error(monkeypatch):
    result, backend = real(
        monkeypatch, "check_service_status", value="Missing", backend=FakeBackend(missing=True),
    )
    assert result.stderr == "Serviço não encontrado."
    assert backend.close_calls == ["MANAGER"]


@pytest.mark.parametrize("forbidden", [
    "binary_path", "service.exe", "private\\account", "password", "credential", "account_name",
    "sid", "registry", "hostname", "username", "domain", "environment", "command_line",
    "arguments", "token", "ip_address", "mac_address",
])
def test_real_output_omits_prohibited_data(monkeypatch, forbidden):
    result, _ = real(monkeypatch, "check_service_status", value="TestSvc")
    assert forbidden not in result.stdout.lower()


@pytest.mark.parametrize("mode", [
    "manager", "enum", "open", "query_status", "query_config", "close",
])
def test_backend_failures_are_generic_and_handles_close(monkeypatch, mode):
    backend = FakeBackend(
        manager_error=mode == "manager", enum_error=mode == "enum",
        open_error=mode == "open", query_status_error=mode == "query_status",
        query_config_error=mode == "query_config", close_error=mode == "close",
    )
    operation = "list_windows_services" if mode == "enum" else "check_service_status"
    value = None if operation == "list_windows_services" else "TestSvc"
    result, backend = real(monkeypatch, operation, value=value, backend=backend)
    assert result.state == LocalExecutionState.FAILED
    assert result.stderr == "Falha ao consultar serviços do Windows."
    assert "sensitive" not in result.stderr
    if mode not in {"manager"}: assert "MANAGER" in backend.close_calls


def test_output_limit_reduces_services_and_keeps_json(monkeypatch):
    records = [(f"Svc{index}", "x" * 100, {"CurrentState": 4}) for index in range(20)]
    sandbox = LocalSandboxPolicy(max_output_bytes=300, max_stderr_bytes=100, max_runtime_seconds=30)
    result, _ = real(monkeypatch, backend=FakeBackend(records=records), sandbox=sandbox)
    assert len(result.stdout.encode()) <= 300 and json.loads(result.stdout)["truncated"] is True
    assert result.output_chunks[0].truncated


def test_sanitize_valid_result_and_output_bytes(monkeypatch):
    raw, _ = real(monkeypatch); result = LocalWindowsServiceAdapter().sanitize(raw)
    assert isinstance(result, LocalSanitizedResult)
    assert result.output_bytes == len(result.stdout_summary.encode()) + len(result.stderr_summary.encode())
    assert result.state == raw.state and result.metadata == {"sanitized": True}


@pytest.mark.parametrize("text,placeholder,reason", [
    (r"C:\\Users\\Private\\service.exe", "[REDACTED_PATH]", RedactionReason.PERSONAL_DATA),
    ("password=hunter2", "password=[REDACTED]", RedactionReason.PASSWORD),
    ("token=abc", "token=[REDACTED]", RedactionReason.TOKEN),
    ("secret=value", "secret=[REDACTED]", RedactionReason.SECRET),
    ("api_key=value", "api_key=[REDACTED]", RedactionReason.API_KEY),
])
def test_sanitize_redacts_residual_sensitive_output(text, placeholder, reason):
    raw = LocalRawExecutionResult(
        command_id="command-1", state=LocalExecutionState.SUCCESS,
        started_at_monotonic=1, finished_at_monotonic=1, exit_code=0,
        stdout=text, stderr="", output_chunks=(), timed_out=False, cancelled=False,
        metadata={"max_output_bytes": 1000},
    )
    result = LocalWindowsServiceAdapter().sanitize(raw)
    assert placeholder in result.stdout_summary and result.redactions[0].reason == reason


def test_sanitize_does_not_requery_backend(monkeypatch):
    raw, _ = real(monkeypatch)
    monkeypatch.setattr("app.services.diagnostic_engine.local_windows_service_adapter._service_backend", FakeBackend(manager_error=True))
    assert LocalWindowsServiceAdapter().sanitize(raw).state == LocalExecutionState.SUCCESS


def test_sanitize_truncates_utf8_safely():
    raw = LocalRawExecutionResult(
        command_id="command-1", state=LocalExecutionState.SUCCESS,
        started_at_monotonic=1, finished_at_monotonic=1, exit_code=0,
        stdout="áéíóú" * 20, stderr="erro", output_chunks=(), timed_out=False,
        cancelled=False, metadata={"max_output_bytes": 17},
    )
    result = LocalWindowsServiceAdapter().sanitize(raw)
    result.stdout_summary.encode("utf-8").decode("utf-8")
    assert result.truncated and result.output_bytes <= 17


@pytest.mark.parametrize("invalid", [None, object(), "raw", 1])
def test_sanitize_rejects_wrong_type(invalid):
    with pytest.raises(ValueError, match="raw_result"):
        LocalWindowsServiceAdapter().sanitize(invalid)


@pytest.mark.parametrize("subject", ["contract", "operation", "command", "sandbox", "arguments"])
def test_execute_does_not_mutate_contract_graph(subject):
    item = contract("check_service_status", value="TestSvc")
    selected = {
        "contract": item, "operation": item.operation, "command": item.command,
        "sandbox": item.sandbox_policy, "arguments": item.command.arguments,
    }[subject]
    before = deepcopy(selected); LocalWindowsServiceAdapter().execute(item, 10)
    assert selected == before


def test_sanitize_does_not_mutate_raw(monkeypatch):
    raw, _ = real(monkeypatch); before = deepcopy(raw)
    LocalWindowsServiceAdapter().sanitize(raw)
    assert raw == before


def test_public_import():
    from app.services.diagnostic_engine import LocalWindowsServiceAdapter as PublicAdapter
    assert PublicAdapter is LocalWindowsServiceAdapter


@pytest.mark.parametrize("name", [
    "subprocess", "os", "socket", "requests", "urllib", "httpx", "pathlib", "winreg", "psutil",
])
def test_adapter_has_no_forbidden_imports(name):
    tree = ast.parse(ADAPTER_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "os.system", "os.popen", "powershell.exe", "cmd.exe", "sc.exe", "net.exe", "wmic",
    "shell=true", "socket.socket", "requests.get", "urllib.request", "startservice(",
    "controlservice(", "changeserviceconfig(", "createservice(", "deleteservice(",
    "setservicestatus(", "open(\"w\"", "unlink(", "remove(",
])
def test_adapter_has_no_forbidden_invocations(text):
    assert text not in ADAPTER_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("path", [ADAPTER_FILE, PACKAGE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
