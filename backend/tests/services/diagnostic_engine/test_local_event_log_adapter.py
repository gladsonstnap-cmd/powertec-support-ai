import ast
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.diagnostic_engine import LocalEventLogAdapter
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalExecutionState, LocalOperationArgument, LocalOperationType,
    LocalRawExecutionResult, LocalSandboxPolicy, LocalSanitizedResult, RedactionReason,
)
from app.services.diagnostic_engine.local_operation_catalog import SafeLocalOperationCatalog


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ADAPTER_FILE = ROOT / "app/services/diagnostic_engine/local_event_log_adapter.py"
PACKAGE = ADAPTER_FILE.with_name("__init__.py")
NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)


def contract(*, log_name="System", hours=None, dry_run=True, sandbox=None, timeout=30):
    arguments = [LocalOperationArgument("log_name", log_name)]
    if hours is not None:
        arguments.append(LocalOperationArgument("hours", hours))
    return SafeLocalOperationCatalog().build_contract(
        contract_id="contract-1", executor_request_id="executor-1", execution_plan_id="plan-1",
        action_id="action-1", grant_id="grant-1", operation_name="collect_event_logs",
        command_id="command-1", arguments=tuple(arguments), dry_run=dry_run,
        timeout_seconds=timeout, sandbox_policy=sandbox,
    )


def event(
    event_id=7031, event_type=1, source="Service Control Manager", timestamp=None,
    category=0, inserts=("Service stopped",), **extra,
):
    values = dict(
        EventID=event_id, EventType=event_type, SourceName=source,
        TimeGenerated=timestamp or NOW, EventCategory=category, StringInserts=inserts,
        ComputerName="PRIVATE-HOST", Sid="PRIVATE-SID", Data=b"private",
    )
    values.update(extra)
    return SimpleNamespace(**values)


class FakeBackend:
    EVENTLOG_BACKWARDS_READ = 8
    EVENTLOG_SEQUENTIAL_READ = 1

    def __init__(self, batches=None, *, open_error=False, read_error=False, close_error=False):
        self.batches = list(batches if batches is not None else [[event()], []])
        self.open_error = open_error
        self.read_error = read_error
        self.close_error = close_error
        self.open_calls = []
        self.read_calls = []
        self.close_calls = []

    def OpenEventLog(self, server, log_name):
        self.open_calls.append((server, log_name))
        if self.open_error:
            raise RuntimeError(r"sensitive C:\\Users\\Private")
        return "HANDLE"

    def ReadEventLog(self, handle, flags, offset):
        self.read_calls.append((handle, flags, offset))
        if self.read_error:
            raise RuntimeError("sensitive read stack")
        return self.batches.pop(0) if self.batches else []

    def CloseEventLog(self, handle):
        self.close_calls.append(handle)
        if self.close_error:
            raise RuntimeError("sensitive close stack")


def real(monkeypatch, *, backend=None, log_name="System", hours=None, sandbox=None):
    selected = backend or FakeBackend()
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_event_log_adapter._event_log_backend", selected,
    )
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_event_log_adapter.platform.system", lambda: "Windows",
    )
    monkeypatch.setattr(LocalEventLogAdapter, "_utc_now", staticmethod(lambda: NOW))
    result = LocalEventLogAdapter().execute(
        contract(log_name=log_name, hours=hours, dry_run=False, sandbox=sandbox), 10,
    )
    return result, selected


def test_constructor_is_frozen_and_has_public_api():
    adapter = LocalEventLogAdapter()
    assert callable(adapter.execute) and callable(adapter.sanitize)
    assert adapter.operation_name == "collect_event_logs"
    with pytest.raises(FrozenInstanceError): adapter.new_state = True


@pytest.mark.parametrize("log_name", ["System", "Application"])
def test_valid_dry_run_contract(log_name):
    result = LocalEventLogAdapter().execute(contract(log_name=log_name), 10)
    assert result.state == LocalExecutionState.SUCCESS and result.exit_code == 0


@pytest.mark.parametrize("invalid", [None, object(), "contract", 1])
def test_invalid_contract_fails_closed(invalid):
    result = LocalEventLogAdapter().execute(invalid, 10)
    assert result.state == LocalExecutionState.FAILED and result.exit_code is None


@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("name", ["read_system_information", "check_disk_space", "unknown"])
def test_wrong_operation_is_rejected(field, name):
    item = contract(); object.__setattr__(getattr(item, field), "operation_name", name)
    assert LocalEventLogAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("adapter", [
    LocalAdapterType.WINDOWS_SERVICE, LocalAdapterType.SYSTEM_INFORMATION,
    LocalAdapterType.PROCESS, LocalAdapterType.NETWORK_DIAGNOSTIC,
    LocalAdapterType.DISK_INFORMATION, LocalAdapterType.FILE_INFORMATION,
    LocalAdapterType.UNKNOWN,
])
def test_wrong_adapter_is_rejected(field, adapter):
    item = contract(); object.__setattr__(getattr(item, field), "adapter_type", adapter)
    assert LocalEventLogAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("target", [
    ExecutionTarget.LOCAL_MACHINE, ExecutionTarget.LINUX, ExecutionTarget.NETWORK,
    ExecutionTarget.REMOTE_AGENT, ExecutionTarget.UNKNOWN,
])
def test_wrong_target_is_rejected(target):
    item = contract(); object.__setattr__(item.command, "target", target)
    assert LocalEventLogAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("risk", [ExecutionRisk.MEDIUM, ExecutionRisk.HIGH, ExecutionRisk.CRITICAL])
def test_wrong_risk_is_rejected(risk):
    item = contract(); object.__setattr__(item.command, "risk", risk)
    assert LocalEventLogAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field", ["operation", "command"])
@pytest.mark.parametrize("kind", [LocalOperationType.STATE_CHANGING, LocalOperationType.DESTRUCTIVE])
def test_wrong_operation_type_is_rejected(field, kind):
    item = contract(); object.__setattr__(getattr(item, field), "operation_type", kind)
    assert LocalEventLogAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("state", [
    LocalExecutionState.BLOCKED, LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS,
    LocalExecutionState.FAILED, LocalExecutionState.CANCELLED, LocalExecutionState.TIMED_OUT,
])
def test_final_or_unsafe_contract_state_is_rejected(state):
    item = contract(); object.__setattr__(item, "state", state)
    assert LocalEventLogAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("state", [LocalExecutionState.PENDING, LocalExecutionState.VALIDATED, LocalExecutionState.READY])
def test_initial_contract_states_are_accepted(state):
    item = contract(); object.__setattr__(item, "state", state)
    assert LocalEventLogAdapter().execute(item, 10).state == LocalExecutionState.SUCCESS


@pytest.mark.parametrize("log_name", [
    "Security", "Setup", "ForwardedEvents", "Microsoft-Windows-Kernel", "Custom",
    "", " ", "system", "SYSTEM", "Application ", "../System", "System/Other",
    "System\\Other", "*.evtx", "?", "System;", "System|", "System&", "System$",
])
def test_non_allowlisted_or_unsafe_log_is_rejected(log_name):
    result = LocalEventLogAdapter().execute(contract(log_name=log_name), 10)
    assert result.state == LocalExecutionState.FAILED


def test_missing_required_log_name_is_rejected():
    item = contract(); object.__setattr__(item.command, "arguments", ())
    assert LocalEventLogAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("hours", [1, 2, 24, 72, 167, 168])
def test_valid_hours_are_accepted(hours):
    assert LocalEventLogAdapter().execute(contract(hours=hours), 10).state == LocalExecutionState.SUCCESS


@pytest.mark.parametrize("hours", [0, -1, 169, 1000, True, False, "24", 1.5, float("nan"), float("inf")])
def test_invalid_hours_are_rejected(hours):
    assert LocalEventLogAdapter().execute(contract(hours=hours), 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("name,value", [
    ("extra", "x"), ("path", r"C:\\private"), ("shell", "x"),
])
def test_extra_argument_is_rejected(name, value):
    item = contract(); object.__setattr__(item.command, "arguments", item.command.arguments + (LocalOperationArgument(name, value),))
    assert LocalEventLogAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("timeout", [0, -1, 31, True, "30"])
def test_invalid_timeout_is_rejected(timeout):
    item = contract(); object.__setattr__(item.command, "timeout_seconds", timeout)
    assert LocalEventLogAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field", [
    "allow_shell", "allow_arbitrary_command", "allow_environment_inheritance",
    "allow_network_access", "allow_filesystem_write", "allow_registry_write",
    "allow_service_state_change", "allow_process_termination", "allow_elevation",
    "allow_child_processes",
])
def test_unsafe_sandbox_is_rejected(field):
    sandbox = replace(LocalSandboxPolicy(), **{field: True})
    assert LocalEventLogAdapter().execute(contract(sandbox=sandbox), 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("invalid", [-1, True, "10", None])
def test_invalid_monotonic_time_is_controlled(invalid):
    result = LocalEventLogAdapter().execute(contract(), invalid)
    assert result.state == LocalExecutionState.FAILED and result.started_at_monotonic is None


def test_dry_run_never_touches_backend(monkeypatch):
    backend = FakeBackend(open_error=True, read_error=True, close_error=True)
    monkeypatch.setattr("app.services.diagnostic_engine.local_event_log_adapter._event_log_backend", backend)
    result = LocalEventLogAdapter().execute(contract(), 10)
    assert result.state == LocalExecutionState.SUCCESS
    assert backend.open_calls == backend.read_calls == backend.close_calls == []


def test_dry_run_shape_and_message():
    result = LocalEventLogAdapter().execute(contract(), 10)
    assert result.stdout == "Dry-run: collect_event_logs validada; nenhum Event Log foi consultado."
    assert result.command_id == "command-1" and result.stderr == "" and result.errors == ()
    assert result.started_at_monotonic == result.finished_at_monotonic == 10
    assert len(result.output_chunks) == 1 and result.output_chunks[0].content == result.stdout


def test_non_windows_real_execution_fails_without_backend(monkeypatch):
    backend = FakeBackend(); monkeypatch.setattr("app.services.diagnostic_engine.local_event_log_adapter._event_log_backend", backend)
    monkeypatch.setattr("app.services.diagnostic_engine.local_event_log_adapter.platform.system", lambda: "Linux")
    result = LocalEventLogAdapter().execute(contract(dry_run=False), 10)
    assert result.state == LocalExecutionState.FAILED and backend.open_calls == []


def test_missing_backend_fails_closed(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.local_event_log_adapter._event_log_backend", None)
    monkeypatch.setattr("app.services.diagnostic_engine.local_event_log_adapter.platform.system", lambda: "Windows")
    result = LocalEventLogAdapter().execute(contract(dry_run=False), 10)
    assert result.stderr == "Backend seguro de Event Log indisponível."


@pytest.mark.parametrize("log_name", ["System", "Application"])
def test_real_backend_opens_exact_allowlisted_log(monkeypatch, log_name):
    result, backend = real(monkeypatch, log_name=log_name)
    assert result.state == LocalExecutionState.SUCCESS
    assert backend.open_calls == [(None, log_name)] and backend.close_calls == ["HANDLE"]
    assert backend.read_calls[0] == ("HANDLE", 9, 0)


@pytest.mark.parametrize("key", [
    "event_id", "severity", "source", "timestamp", "category", "message_summary", "log_name",
])
def test_each_allowed_event_field_is_present(monkeypatch, key):
    result, _ = real(monkeypatch)
    assert key in json.loads(result.stdout)["events"][0]


@pytest.mark.parametrize("forbidden", [
    "computer", "hostname", "user", "username", "sid", "binary", "data", "raw_xml",
    "domain", "environment", "product_key", "serial", "credential", "cookie",
])
def test_real_output_omits_private_event_fields(monkeypatch, forbidden):
    result, _ = real(monkeypatch)
    assert forbidden not in result.stdout.lower()


@pytest.mark.parametrize("event_type,expected", [
    (1, "error"), (2, "warning"), (4, "information"), (8, "audit_success"),
    (16, "audit_failure"), (0, "unknown"), (999, "unknown"),
])
def test_event_severity_mapping(monkeypatch, event_type, expected):
    result, _ = real(monkeypatch, backend=FakeBackend([[event(event_type=event_type)], []]))
    assert json.loads(result.stdout)["events"][0]["severity"] == expected


def test_event_id_is_reduced_to_windows_identifier(monkeypatch):
    result, _ = real(monkeypatch, backend=FakeBackend([[event(event_id=0xC0001B77)], []]))
    assert json.loads(result.stdout)["events"][0]["event_id"] == 0x1B77


def test_empty_backend_result_is_success(monkeypatch):
    result, _ = real(monkeypatch, backend=FakeBackend([[]]))
    assert json.loads(result.stdout)["event_count"] == 0


def test_missing_source_and_timestamp_are_safe(monkeypatch):
    item = event(); del item.SourceName; del item.TimeGenerated
    result, _ = real(monkeypatch, backend=FakeBackend([[item], []]))
    projected = json.loads(result.stdout)["events"][0]
    assert projected["source"] == "" and projected["timestamp"] == ""


def test_duplicate_events_are_deduplicated(monkeypatch):
    item = event(); result, _ = real(monkeypatch, backend=FakeBackend([[item, item], []]))
    assert json.loads(result.stdout)["event_count"] == 1


def test_events_keep_backend_newest_first_order(monkeypatch):
    items = [event(event_id=3), event(event_id=2), event(event_id=1)]
    result, _ = real(monkeypatch, backend=FakeBackend([items, []]))
    assert [item["event_id"] for item in json.loads(result.stdout)["events"]] == [3, 2, 1]


def test_old_event_stops_pagination(monkeypatch):
    old = event(timestamp=NOW - timedelta(hours=25))
    backend = FakeBackend([[event(event_id=1), old], [event(event_id=2)], []])
    result, backend = real(monkeypatch, backend=backend, hours=24)
    assert [item["event_id"] for item in json.loads(result.stdout)["events"]] == [1]
    assert len(backend.read_calls) == 1


def test_max_events_stops_collection(monkeypatch):
    items = [event(event_id=index, source=f"source-{index}") for index in range(150)]
    result, backend = real(monkeypatch, backend=FakeBackend([items, []]))
    assert json.loads(result.stdout)["event_count"] == LocalEventLogAdapter.MAX_EVENTS
    assert len(backend.read_calls) == 1


@pytest.mark.parametrize("message,placeholder", [
    (r"failure C:\\Users\\Private\\secret.txt", "[REDACTED_PATH]"),
    (r"failure \\\\server\\share\\private.txt", "[REDACTED_PATH]"),
    ("password=hunter2", "password=[REDACTED]"),
    ("token=abc", "token=[REDACTED]"),
    ("secret=value", "secret=[REDACTED]"),
    ("api_key=value", "api_key=[REDACTED]"),
])
def test_message_summary_redacts_obvious_sensitive_content(monkeypatch, message, placeholder):
    result, _ = real(monkeypatch, backend=FakeBackend([[event(inserts=(message,))], []]))
    summary = json.loads(result.stdout)["events"][0]["message_summary"]
    assert placeholder in summary and "hunter2" not in summary and "Private" not in summary


def test_message_summary_is_length_limited(monkeypatch):
    result, _ = real(monkeypatch, backend=FakeBackend([[event(inserts=("x" * 1000,))], []]))
    assert len(json.loads(result.stdout)["events"][0]["message_summary"]) == 500


@pytest.mark.parametrize("mode", ["open", "read", "close"])
def test_backend_failure_is_generic_and_handle_is_closed_when_opened(monkeypatch, mode):
    backend = FakeBackend(
        open_error=mode == "open", read_error=mode == "read", close_error=mode == "close",
    )
    result, backend = real(monkeypatch, backend=backend)
    assert result.state == LocalExecutionState.FAILED
    assert result.stderr == "Falha ao coletar eventos do Windows."
    assert "sensitive" not in result.stderr
    if mode != "open": assert backend.close_calls == ["HANDLE"]


def test_output_limit_reduces_events_and_keeps_json(monkeypatch):
    events = [event(event_id=index, source=f"source-{index}", inserts=("x" * 100,)) for index in range(20)]
    sandbox = LocalSandboxPolicy(max_output_bytes=300, max_stderr_bytes=100, max_runtime_seconds=30)
    result, _ = real(monkeypatch, backend=FakeBackend([events, []]), sandbox=sandbox)
    assert len(result.stdout.encode()) <= 300 and json.loads(result.stdout)["truncated"] is True
    assert result.output_chunks[0].truncated


def test_sanitize_valid_result_and_output_bytes(monkeypatch):
    raw, _ = real(monkeypatch); result = LocalEventLogAdapter().sanitize(raw)
    assert isinstance(result, LocalSanitizedResult)
    assert result.output_bytes == len(result.stdout_summary.encode()) + len(result.stderr_summary.encode())
    assert result.state == raw.state and result.metadata == {"sanitized": True}


def test_sanitize_redacts_residual_path_and_secret():
    raw = LocalRawExecutionResult(
        command_id="command-1", state=LocalExecutionState.SUCCESS,
        started_at_monotonic=1, finished_at_monotonic=1, exit_code=0,
        stdout=r"C:\\Users\\Private token=abc", stderr="", output_chunks=(),
        timed_out=False, cancelled=False, metadata={"max_output_bytes": 1000},
    )
    result = LocalEventLogAdapter().sanitize(raw)
    assert "Private" not in result.stdout_summary and "abc" not in result.stdout_summary
    assert {item.reason for item in result.redactions} == {RedactionReason.PERSONAL_DATA, RedactionReason.TOKEN}


def test_sanitize_does_not_recollect(monkeypatch):
    raw, _ = real(monkeypatch)
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_event_log_adapter._event_log_backend",
        FakeBackend(open_error=True),
    )
    assert LocalEventLogAdapter().sanitize(raw).state == LocalExecutionState.SUCCESS


def test_sanitize_truncates_utf8_safely():
    raw = LocalRawExecutionResult(
        command_id="command-1", state=LocalExecutionState.SUCCESS,
        started_at_monotonic=1, finished_at_monotonic=1, exit_code=0,
        stdout="áéíóú" * 20, stderr="erro", output_chunks=(), timed_out=False,
        cancelled=False, metadata={"max_output_bytes": 17},
    )
    result = LocalEventLogAdapter().sanitize(raw)
    result.stdout_summary.encode("utf-8").decode("utf-8")
    assert result.truncated and result.output_bytes <= 17


@pytest.mark.parametrize("invalid", [None, object(), "raw", 1])
def test_sanitize_rejects_wrong_type(invalid):
    with pytest.raises(ValueError, match="raw_result"):
        LocalEventLogAdapter().sanitize(invalid)


@pytest.mark.parametrize("subject", ["contract", "operation", "command", "sandbox", "arguments"])
def test_execute_does_not_mutate_contract_graph(subject):
    item = contract(hours=24); selected = {
        "contract": item, "operation": item.operation, "command": item.command,
        "sandbox": item.sandbox_policy, "arguments": item.command.arguments,
    }[subject]
    before = deepcopy(selected); LocalEventLogAdapter().execute(item, 10)
    assert selected == before


def test_sanitize_does_not_mutate_raw(monkeypatch):
    raw, _ = real(monkeypatch); before = deepcopy(raw)
    LocalEventLogAdapter().sanitize(raw)
    assert raw == before


def test_public_import():
    from app.services.diagnostic_engine import LocalEventLogAdapter as PublicAdapter
    assert PublicAdapter is LocalEventLogAdapter


@pytest.mark.parametrize("name", [
    "subprocess", "os", "socket", "requests", "urllib", "httpx", "pathlib", "winreg",
])
def test_adapter_has_no_forbidden_imports(name):
    tree = ast.parse(ADAPTER_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("text", [
    "os.system", "os.popen", "powershell.exe", "pwsh", "cmd.exe", "wmic", "wevtutil",
    "shell=true", "socket.socket", "requests.get", "urllib.request", "cleareventlog",
    "backupeventlog", "registereventsource", "open(\"w\"", "unlink(", "remove(",
])
def test_adapter_has_no_forbidden_invocations(text):
    assert text not in ADAPTER_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("path", [ADAPTER_FILE, PACKAGE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
