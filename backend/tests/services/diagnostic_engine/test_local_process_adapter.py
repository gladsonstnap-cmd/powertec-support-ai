import ast
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import LocalProcessAdapter
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalExecutionState, LocalOperationArgument, LocalOperationType,
    LocalRawExecutionResult, LocalSandboxPolicy, LocalSanitizedResult, OutputStreamType,
)
from app.services.diagnostic_engine.local_operation_catalog import SafeLocalOperationCatalog


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ADAPTER_FILE = ROOT / "app/services/diagnostic_engine/local_process_adapter.py"
PACKAGE_FILE = ADAPTER_FILE.with_name("__init__.py")
OPERATIONS = ("list_processes", "read_system_process_information")
DRY_MESSAGE = "Dry-run: operação de processos validada; nenhuma consulta real foi realizada."


def contract(operation="list_processes", *, value=None, dry_run=True, sandbox=None):
    arguments = ()
    if value is not None:
        name = "name_filter" if operation == "list_processes" else "process_name"
        arguments = (LocalOperationArgument(name, value, required=operation != "list_processes"),)
    return SafeLocalOperationCatalog().build_contract(
        contract_id="contract-1", executor_request_id="executor-1",
        execution_plan_id="plan-1", action_id="action-1", grant_id="grant-1",
        operation_name=operation, command_id="command-1", arguments=arguments,
        dry_run=dry_run, sandbox_policy=sandbox,
    )


class FakeProcess:
    def __init__(self, info=None, error=None):
        self._info = info
        self._error = error

    @property
    def info(self):
        if self._error is not None:
            raise self._error
        return self._info


class NoSuchProcess(Exception):
    pass


class AccessDenied(Exception):
    pass


class ZombieProcess(Exception):
    pass


class FakeBackend:
    def __init__(self, records=(), error=None):
        self.records = list(records)
        self.error = error
        self.calls = []

    def process_iter(self, *, attrs, ad_value):
        self.calls.append((attrs, ad_value))
        if self.error is not None:
            raise self.error
        return iter(self.records)


def run_real(monkeypatch, operation="list_processes", *, value=None, records=(), error=None,
             sandbox=None):
    backend = FakeBackend(records, error)
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_process_adapter._process_backend", backend
    )
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_process_adapter.platform.system", lambda: "Windows"
    )
    result = LocalProcessAdapter().execute(
        contract(operation, value=value, dry_run=False, sandbox=sandbox), 10
    )
    return backend, result


def payload(result):
    return json.loads(result.stdout)


def test_construction_is_public_and_frozen():
    adapter = LocalProcessAdapter()
    assert isinstance(adapter, LocalProcessAdapter)
    with pytest.raises(FrozenInstanceError):
        adapter.MAX_PROCESSES = 1


@pytest.mark.parametrize("operation,value", [
    ("list_processes", None), ("list_processes", "python"),
    ("read_system_process_information", "python.exe"),
])
def test_dry_run_succeeds_without_backend(monkeypatch, operation, value):
    class ForbiddenBackend:
        def __getattr__(self, name):
            raise AssertionError("backend must not be called")
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_process_adapter._process_backend", ForbiddenBackend()
    )
    result = LocalProcessAdapter().execute(contract(operation, value=value), 10)
    assert result.state == LocalExecutionState.SUCCESS and result.stdout == DRY_MESSAGE
    assert result.stderr == "" and result.exit_code == 0
    assert len(result.output_chunks) == 1
    assert result.output_chunks[0].stream == OutputStreamType.STDOUT


@pytest.mark.parametrize("operation", OPERATIONS)
def test_backend_absent_real_execution_fails_closed(monkeypatch, operation):
    monkeypatch.setattr("app.services.diagnostic_engine.local_process_adapter._process_backend", None)
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_process_adapter.platform.system", lambda: "Windows"
    )
    value = None if operation == "list_processes" else "python.exe"
    result = LocalProcessAdapter().execute(contract(operation, value=value, dry_run=False), 10)
    assert result.state == LocalExecutionState.FAILED
    assert result.stderr == "Backend seguro de processos indisponível."


@pytest.mark.parametrize("system", ["Linux", "Darwin", "FreeBSD", "Unknown"])
@pytest.mark.parametrize("operation", OPERATIONS)
def test_non_windows_real_execution_fails_before_backend(monkeypatch, system, operation):
    backend = FakeBackend()
    monkeypatch.setattr("app.services.diagnostic_engine.local_process_adapter._process_backend", backend)
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_process_adapter.platform.system", lambda: system
    )
    value = None if operation == "list_processes" else "python.exe"
    result = LocalProcessAdapter().execute(contract(operation, value=value, dry_run=False), 10)
    assert result.state == LocalExecutionState.FAILED and not backend.calls


@pytest.mark.parametrize("records", [
    [],
    [FakeProcess({"pid": 2, "name": "beta.exe", "status": "sleeping"})],
    [
        FakeProcess({"pid": 3, "name": "Zulu.exe", "status": "running"}),
        FakeProcess({"pid": 2, "name": "alpha.exe", "status": "stopped"}),
        FakeProcess({"pid": 1, "name": "Alpha.exe", "status": "idle"}),
    ],
])
def test_list_processes_is_structured_and_deterministic(monkeypatch, records):
    backend, result = run_real(monkeypatch, records=records)
    data = payload(result)
    assert result.state == LocalExecutionState.SUCCESS
    assert data["operation"] == "list_processes"
    assert data["process_count"] == len(data["processes"])
    assert data["processes"] == sorted(
        data["processes"], key=lambda item: (item["process_name"].casefold(), item["pid"])
    )
    assert backend.calls == [(('pid', 'name', 'status'), None)]


@pytest.mark.parametrize("name_filter,expected", [
    ("python", [3, 1]), ("PYTHON", [3, 1]), ("thon", [3, 1]),
    ("other", [2]), ("missing", []), ("exe", [2, 3, 1]),
])
def test_name_filter_is_case_insensitive_substring(monkeypatch, name_filter, expected):
    records = [
        FakeProcess({"pid": 3, "name": "Python.exe", "status": "running"}),
        FakeProcess({"pid": 2, "name": "other.exe", "status": "sleeping"}),
        FakeProcess({"pid": 1, "name": "pythonw.exe", "status": "running"}),
    ]
    _, result = run_real(monkeypatch, value=name_filter, records=records)
    assert [item["pid"] for item in payload(result)["processes"]] == expected


def test_process_limit_is_enforced(monkeypatch):
    records = [
        FakeProcess({"pid": index, "name": f"process-{index:03}.exe", "status": "running"})
        for index in range(LocalProcessAdapter.MAX_PROCESSES + 25)
    ]
    _, result = run_real(monkeypatch, records=records)
    assert payload(result)["process_count"] == LocalProcessAdapter.MAX_PROCESSES


@pytest.mark.parametrize("query,expected", [
    ("python.exe", [1, 3]), ("PYTHON.EXE", [1, 3]),
    ("other.exe", [2]), ("missing.exe", []),
])
def test_process_information_uses_exact_case_insensitive_match(monkeypatch, query, expected):
    records = [
        FakeProcess({"pid": 3, "name": "Python.exe", "status": "running"}),
        FakeProcess({"pid": 2, "name": "other.exe", "status": "sleeping"}),
        FakeProcess({"pid": 1, "name": "python.exe", "status": "stopped"}),
        FakeProcess({"pid": 4, "name": "pythonw.exe", "status": "running"}),
    ]
    _, result = run_real(
        monkeypatch, "read_system_process_information", value=query, records=records
    )
    data = payload(result)
    assert data["process_name"] == query and data["match_count"] == len(expected)
    assert [item["pid"] for item in data["processes"]] == expected


@pytest.mark.parametrize("status,expected", [
    ("running", "running"), ("sleeping", "sleeping"), ("stopped", "stopped"),
    ("zombie", "zombie"), ("idle", "idle"), ("disk-sleep", "disk_sleep"),
    ("disk_sleep", "disk_sleep"), ("dead", "dead"), ("waiting", "unknown"),
    (None, "unknown"), (1, "unknown"), ("", "unknown"),
])
def test_status_is_canonical(monkeypatch, status, expected):
    records = [FakeProcess({"pid": 1, "name": "safe.exe", "status": status})]
    _, result = run_real(monkeypatch, records=records)
    assert payload(result)["processes"][0]["status"] == expected


@pytest.mark.parametrize("info", [
    None, [], "bad", {}, {"pid": None, "name": "a", "status": "running"},
    {"pid": True, "name": "a", "status": "running"},
    {"pid": -1, "name": "a", "status": "running"},
    {"pid": 1, "name": None, "status": "running"},
    {"pid": 1, "name": "", "status": "running"},
    {"pid": 1, "name": "   ", "status": "running"},
])
def test_malformed_backend_records_are_ignored(monkeypatch, info):
    records = [FakeProcess(info), FakeProcess({"pid": 2, "name": "safe.exe", "status": "running"})]
    _, result = run_real(monkeypatch, records=records)
    assert payload(result)["processes"] == [
        {"pid": 2, "process_name": "safe.exe", "status": "running"}
    ]


@pytest.mark.parametrize("error", [NoSuchProcess(), AccessDenied(), ZombieProcess(), RuntimeError("secret stack")])
def test_individual_process_errors_are_ignored(monkeypatch, error):
    records = [
        FakeProcess(error=error),
        FakeProcess({"pid": 2, "name": "safe.exe", "status": "running"}),
    ]
    _, result = run_real(monkeypatch, records=records)
    assert result.state == LocalExecutionState.SUCCESS
    assert payload(result)["process_count"] == 1
    assert "secret" not in result.stdout.lower()


@pytest.mark.parametrize("error", [RuntimeError("secret stack"), ValueError("private path"), OSError("denied")])
def test_global_backend_failure_is_generic(monkeypatch, error):
    _, result = run_real(monkeypatch, error=error)
    assert result.state == LocalExecutionState.FAILED
    assert result.stderr == "Falha ao consultar processos do Windows."
    assert "secret" not in result.stderr.lower() and "private" not in result.stderr.lower()


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("adapter_type", [
    LocalAdapterType.UNKNOWN, LocalAdapterType.SYSTEM_INFORMATION,
    LocalAdapterType.DISK_INFORMATION, LocalAdapterType.WINDOWS_SERVICE,
    LocalAdapterType.WINDOWS_EVENT_LOG, LocalAdapterType.NETWORK_DIAGNOSTIC,
])
def test_wrong_adapter_fails_closed(operation, field, adapter_type):
    value = None if operation == "list_processes" else "safe.exe"
    item = contract(operation, value=value)
    object.__setattr__(getattr(item, field), "adapter_type", adapter_type)
    assert LocalProcessAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("target", [
    ExecutionTarget.LOCAL_MACHINE, ExecutionTarget.LINUX, ExecutionTarget.NETWORK,
    ExecutionTarget.REMOTE_AGENT, ExecutionTarget.UNKNOWN,
])
def test_wrong_target_fails_closed(operation, target):
    value = None if operation == "list_processes" else "safe.exe"
    item = contract(operation, value=value); object.__setattr__(item.command, "target", target)
    assert LocalProcessAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("risk", [ExecutionRisk.MEDIUM, ExecutionRisk.HIGH, ExecutionRisk.CRITICAL])
def test_wrong_risk_fails_closed(operation, risk):
    value = None if operation == "list_processes" else "safe.exe"
    item = contract(operation, value=value); object.__setattr__(item.command, "risk", risk)
    assert LocalProcessAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("kind", [LocalOperationType.STATE_CHANGING, LocalOperationType.DESTRUCTIVE])
def test_mutable_types_fail_closed(operation, field, kind):
    value = None if operation == "list_processes" else "safe.exe"
    item = contract(operation, value=value)
    object.__setattr__(getattr(item, field), "operation_type", kind)
    assert LocalProcessAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("state", [
    LocalExecutionState.BLOCKED, LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS,
    LocalExecutionState.FAILED, LocalExecutionState.CANCELLED, LocalExecutionState.TIMED_OUT,
])
def test_invalid_contract_states_fail_closed(state):
    item = contract(); object.__setattr__(item, "state", state)
    assert LocalProcessAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("timeout", [0, -1, 31, 61, True, "30", None])
def test_invalid_timeouts_fail_closed(timeout):
    item = contract(); object.__setattr__(item.command, "timeout_seconds", timeout)
    assert LocalProcessAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field", [
    "allow_shell", "allow_arbitrary_command", "allow_environment_inheritance",
    "allow_network_access", "allow_filesystem_write", "allow_registry_write",
    "allow_service_state_change", "allow_process_termination", "allow_elevation",
    "allow_child_processes",
])
def test_unsafe_sandbox_fails_closed(field):
    item = contract(sandbox=replace(LocalSandboxPolicy(), **{field: True}))
    assert LocalProcessAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("value", [
    "", " ", " leading", "trailing ", "*", "?", "[abc]", ";", "|", "&", "`",
    "$", ">", "<", "C:\\Windows", "../proc", "name/process", "x" * 129, 1, True,
])
def test_invalid_filter_and_process_names_fail_closed(operation, value):
    item = contract(operation, value="safe.exe" if operation != "list_processes" else None)
    name = "name_filter" if operation == "list_processes" else "process_name"
    object.__setattr__(item.command, "arguments", (LocalOperationArgument(name, value),))
    assert LocalProcessAdapter().execute(item, 10).state == LocalExecutionState.FAILED


def test_required_process_name_is_enforced():
    item = contract("read_system_process_information", value="safe.exe")
    object.__setattr__(item.command, "arguments", ())
    assert LocalProcessAdapter().execute(item, 10).state == LocalExecutionState.FAILED


def test_output_contains_only_allowlisted_fields(monkeypatch):
    info = {
        "pid": 1, "name": "safe.exe", "status": "running", "username": "secret",
        "cmdline": ["secret"], "exe": "C:\\secret.exe", "cwd": "C:\\private",
        "environ": {"token": "x"}, "connections": ["x"], "open_files": ["x"],
    }
    _, result = run_real(monkeypatch, records=[FakeProcess(info)])
    assert set(payload(result)["processes"][0]) == {"pid", "process_name", "status"}
    assert "secret" not in result.stdout and "C:\\" not in result.stdout


def test_sanitize_redacts_paths_and_secrets_without_recollection():
    text = r'C:\Users\Private \\server\share password=hunter token=abc secret=value api_key=key'
    source = LocalRawExecutionResult(
        command_id="command-1", state=LocalExecutionState.FAILED,
        started_at_monotonic=1, finished_at_monotonic=1, exit_code=None,
        stdout=text, stderr=text, output_chunks=(), timed_out=False, cancelled=False,
        errors=("generic",), metadata={"max_output_bytes": 4096},
    )
    before = deepcopy(source); result = LocalProcessAdapter().sanitize(source)
    assert source == before and isinstance(result, LocalSanitizedResult)
    assert "Private" not in result.stdout_summary and "hunter" not in result.stdout_summary
    assert result.redactions and result.output_bytes == len(result.stdout_summary.encode()) + len(result.stderr_summary.encode())


@pytest.mark.parametrize("limit", [1, 5, 16, 32, 64, 128])
def test_sanitize_truncates_on_utf8_boundaries(limit):
    source = LocalRawExecutionResult(
        command_id="command-1", state=LocalExecutionState.SUCCESS,
        started_at_monotonic=1, finished_at_monotonic=1, exit_code=0,
        stdout="processo-ção-" * 30, stderr="", output_chunks=(),
        timed_out=False, cancelled=False, metadata={"max_output_bytes": limit},
    )
    result = LocalProcessAdapter().sanitize(source)
    assert result.output_bytes <= limit and result.truncated
    result.stdout_summary.encode("utf-8")


@pytest.mark.parametrize("invalid", [None, object(), "raw", 1, True])
def test_sanitize_rejects_invalid_input(invalid):
    with pytest.raises(ValueError, match="raw_result"):
        LocalProcessAdapter().sanitize(invalid)


@pytest.mark.parametrize("subject", ["contract", "operation", "command", "arguments", "sandbox"])
def test_execute_does_not_mutate_contract_graph(subject):
    item = contract("read_system_process_information", value="safe.exe")
    selected = {
        "contract": item, "operation": item.operation, "command": item.command,
        "arguments": item.command.arguments, "sandbox": item.sandbox_policy,
    }[subject]
    before = deepcopy(selected); LocalProcessAdapter().execute(item, 10)
    assert selected == before


@pytest.mark.parametrize("name", ["subprocess", "socket", "requests", "httpx"])
def test_adapter_has_no_forbidden_imports(name):
    tree = ast.parse(ADAPTER_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "os.system", "os.popen", "powershell.exe", "cmd.exe", "tasklist", "taskkill", "wmic",
    "createprocess", "openprocess", "terminateprocess", ".terminate(", ".kill(",
    ".suspend(", ".resume(", ".nice(", ".cpu_affinity(", ".ionice(",
    "debugactiveprocess", "socket.socket", "requests.get", "httpx.get", ".cmdline(",
    ".username(", ".environ(", ".memory_maps(", ".open_files(", ".connections(",
])
def test_adapter_has_no_mutating_or_forbidden_calls(text):
    assert text not in ADAPTER_FILE.read_text(encoding="utf-8").lower()


def test_operation_set_is_exact_and_immutable():
    assert LocalProcessAdapter.operation_names == frozenset(OPERATIONS)


@pytest.mark.parametrize("path", [ADAPTER_FILE, PACKAGE_FILE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes()
    assert not content.startswith(b"\xef\xbb\xbf")
    content.decode("utf-8")
