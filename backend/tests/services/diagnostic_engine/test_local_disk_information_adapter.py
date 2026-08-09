import ast
import json
from collections import namedtuple
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import LocalDiskInformationAdapter
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalExecutionState, LocalOperationArgument, LocalOperationType,
    LocalRawExecutionResult, LocalSandboxPolicy, LocalSanitizedResult, RedactionReason,
)
from app.services.diagnostic_engine.local_operation_catalog import SafeLocalOperationCatalog


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ADAPTER_FILE = ROOT / "app/services/diagnostic_engine/local_disk_information_adapter.py"
PACKAGE = ADAPTER_FILE.with_name("__init__.py")
DiskUsage = namedtuple("DiskUsage", "total used free")


def contract(operation="check_disk_space", *, value=None, dry_run=True, sandbox=None, timeout=30):
    argument_name = "drive" if operation == "check_disk_space" else "disk_name"
    arguments = () if value is None else (LocalOperationArgument(argument_name, value),)
    return SafeLocalOperationCatalog().build_contract(
        contract_id="contract-1", executor_request_id="executor-1", execution_plan_id="plan-1",
        action_id="action-1", grant_id="grant-1", operation_name=operation,
        command_id="command-1", arguments=arguments, dry_run=dry_run,
        timeout_seconds=timeout, sandbox_policy=sandbox,
    )


def real(monkeypatch, operation="check_disk_space", *, value="C:", usage=(100, 25, 75)):
    calls = []
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_disk_information_adapter.platform.system",
        lambda: "Windows",
    )
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_disk_information_adapter.shutil.disk_usage",
        lambda target: calls.append(target) or DiskUsage(*usage),
    )
    result = LocalDiskInformationAdapter().execute(
        contract(operation, value=value, dry_run=False), 10.0
    )
    return result, calls


def test_constructor_and_public_methods():
    adapter = LocalDiskInformationAdapter()
    assert callable(adapter.execute) and callable(adapter.sanitize)
    assert adapter.operation_names == {"check_disk_information", "check_disk_space"}


@pytest.mark.parametrize("operation", ["check_disk_information", "check_disk_space"])
def test_valid_dry_run_contract(operation):
    result = LocalDiskInformationAdapter().execute(contract(operation), 10)
    assert result.state == LocalExecutionState.SUCCESS and result.exit_code == 0


@pytest.mark.parametrize("invalid", [None, object(), "contract", 1])
def test_invalid_contract_fails_closed(invalid):
    result = LocalDiskInformationAdapter().execute(invalid, 10)
    assert result.state == LocalExecutionState.FAILED and result.exit_code is None


@pytest.mark.parametrize("field_name", ["operation", "command"])
@pytest.mark.parametrize("value", ["read_system_information", "ping_host"])
def test_wrong_operation_is_rejected(field_name, value):
    item = contract(); object.__setattr__(getattr(item, field_name), "operation_name", value)
    assert LocalDiskInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field_name", ["operation", "command"])
@pytest.mark.parametrize("adapter", [LocalAdapterType.PROCESS, LocalAdapterType.UNKNOWN, LocalAdapterType.SYSTEM_INFORMATION])
def test_wrong_adapter_is_rejected(field_name, adapter):
    item = contract(); object.__setattr__(getattr(item, field_name), "adapter_type", adapter)
    assert LocalDiskInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("target", [ExecutionTarget.NETWORK, ExecutionTarget.LINUX, ExecutionTarget.UNKNOWN])
def test_wrong_target_is_rejected(target):
    item = contract(); object.__setattr__(item.command, "target", target)
    assert LocalDiskInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("risk", [ExecutionRisk.MEDIUM, ExecutionRisk.HIGH, ExecutionRisk.CRITICAL])
def test_wrong_risk_is_rejected(risk):
    item = contract(); object.__setattr__(item.command, "risk", risk)
    assert LocalDiskInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("operation_type", [LocalOperationType.STATE_CHANGING, LocalOperationType.DESTRUCTIVE])
def test_wrong_operation_type_is_rejected(operation_type):
    item = contract(); object.__setattr__(item.command, "operation_type", operation_type)
    assert LocalDiskInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("state", [
    LocalExecutionState.BLOCKED, LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS,
    LocalExecutionState.FAILED, LocalExecutionState.CANCELLED, LocalExecutionState.TIMED_OUT,
])
def test_incompatible_contract_state_is_rejected(state):
    item = contract(); object.__setattr__(item, "state", state)
    assert LocalDiskInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("state", [LocalExecutionState.PENDING, LocalExecutionState.VALIDATED, LocalExecutionState.READY])
def test_structural_contract_states_are_accepted(state):
    item = contract(); object.__setattr__(item, "state", state)
    assert LocalDiskInformationAdapter().execute(item, 10).state == LocalExecutionState.SUCCESS


@pytest.mark.parametrize("operation", ["check_disk_information", "check_disk_space"])
def test_optional_argument_may_be_absent(operation):
    assert LocalDiskInformationAdapter().execute(contract(operation), 10).state == LocalExecutionState.SUCCESS


@pytest.mark.parametrize("operation,value", [
    ("check_disk_information", "C:"), ("check_disk_information", "z:"),
    ("check_disk_space", "D:"), ("check_disk_space", "x:"),
])
def test_valid_drive_identifier_is_accepted(operation, value):
    assert LocalDiskInformationAdapter().execute(contract(operation, value=value), 10).state == LocalExecutionState.SUCCESS


@pytest.mark.parametrize("value", [
    "", "C", "CC:", "C:\\", "C:/", "../C:", "..", "/", "\\", "*", "?",
    "C:*", "C:?", "C:;", "C:|", "C:&", "C:>", "C:<", "C:`", "C:$",
])
@pytest.mark.parametrize("operation", ["check_disk_information", "check_disk_space"])
def test_unsafe_or_unstructured_identifier_is_rejected(operation, value):
    result = LocalDiskInformationAdapter().execute(contract(operation, value=value), 10)
    assert result.state == LocalExecutionState.FAILED


@pytest.mark.parametrize("operation,wrong_name", [
    ("check_disk_information", "drive"), ("check_disk_space", "disk_name"),
])
def test_wrong_argument_name_is_rejected(operation, wrong_name):
    item = contract(operation); object.__setattr__(item.command, "arguments", (LocalOperationArgument(wrong_name, "C:"),))
    assert LocalDiskInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("operation", ["check_disk_information", "check_disk_space"])
def test_extra_argument_is_rejected(operation):
    item = contract(operation, value="C:")
    object.__setattr__(item.command, "arguments", item.command.arguments + (LocalOperationArgument("extra", "x"),))
    assert LocalDiskInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("timeout", [0, -1, 31, True, "30"])
def test_invalid_timeout_is_rejected(timeout):
    item = contract(); object.__setattr__(item.command, "timeout_seconds", timeout)
    assert LocalDiskInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field_name", [
    "allow_shell", "allow_arbitrary_command", "allow_environment_inheritance",
    "allow_network_access", "allow_filesystem_write", "allow_registry_write",
    "allow_service_state_change", "allow_process_termination", "allow_elevation",
    "allow_child_processes",
])
def test_incompatible_sandbox_capability_is_rejected(field_name):
    item = contract(sandbox=replace(LocalSandboxPolicy(), **{field_name: True}))
    assert LocalDiskInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("invalid", [-1, True, "10", None])
def test_invalid_monotonic_time_is_controlled(invalid):
    result = LocalDiskInformationAdapter().execute(contract(), invalid)
    assert result.state == LocalExecutionState.FAILED and result.started_at_monotonic is None


@pytest.mark.parametrize("operation", ["check_disk_information", "check_disk_space"])
def test_dry_run_never_calls_real_disk_apis(monkeypatch, operation):
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_disk_information_adapter.shutil.disk_usage",
        lambda target: (_ for _ in ()).throw(AssertionError("disk read must not run")),
    )
    monkeypatch.setattr(
        LocalDiskInformationAdapter, "_system_drive",
        lambda: (_ for _ in ()).throw(AssertionError("drive discovery must not run")),
    )
    assert LocalDiskInformationAdapter().execute(contract(operation), 10).state == LocalExecutionState.SUCCESS


@pytest.mark.parametrize("operation", ["check_disk_information", "check_disk_space"])
def test_dry_run_exact_message_and_raw_shape(operation):
    result = LocalDiskInformationAdapter().execute(contract(operation), 10)
    assert result.stdout == "Dry-run: operação de disco validada; nenhuma leitura real foi realizada."
    assert result.command_id == "command-1" and result.stderr == ""
    assert result.started_at_monotonic == result.finished_at_monotonic == 10
    assert not result.timed_out and not result.cancelled and result.errors == ()
    assert len(result.output_chunks) == 1 and result.output_chunks[0].content == result.stdout


@pytest.mark.parametrize("key,expected", [
    ("drive", "C:"), ("total_bytes", 100), ("used_bytes", 25),
    ("free_bytes", 75), ("usage_percent", 25.0),
])
def test_disk_space_fields(monkeypatch, key, expected):
    result, calls = real(monkeypatch)
    assert json.loads(result.stdout)[key] == expected and calls == ["C:\\"]


def test_disk_space_total_zero_is_safe(monkeypatch):
    result, _ = real(monkeypatch, usage=(0, 0, 0))
    assert json.loads(result.stdout)["usage_percent"] == 0.0


@pytest.mark.parametrize("key,expected", [
    ("device", "C:"), ("mountpoint", "C:"), ("filesystem_type", ""),
    ("total_bytes", 100), ("used_bytes", 25), ("free_bytes", 75),
])
def test_disk_information_fields(monkeypatch, key, expected):
    result, calls = real(monkeypatch, "check_disk_information")
    assert json.loads(result.stdout)[key] == expected and calls == ["C:\\"]


@pytest.mark.parametrize("operation,value", [
    ("check_disk_information", "D:"), ("check_disk_space", "Z:"),
])
def test_explicit_filter_is_exact_and_preserved(monkeypatch, operation, value):
    result, calls = real(monkeypatch, operation, value=value)
    data = json.loads(result.stdout)
    assert calls == [f"{value.upper()}\\"]
    assert data.get("device", data.get("drive")) == value.upper()


@pytest.mark.parametrize("operation", ["check_disk_information", "check_disk_space"])
def test_real_json_is_compact_sorted_and_deterministic(monkeypatch, operation):
    first, _ = real(monkeypatch, operation); second, _ = real(monkeypatch, operation)
    assert first == second
    assert first.stdout == json.dumps(json.loads(first.stdout), sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize("operation", ["check_disk_information", "check_disk_space"])
@pytest.mark.parametrize("forbidden", [
    "serial", "username", "home", "environment", "token", "credential", "password",
    "ip_address", "mac_address", "filename", "firmware", "product_key",
])
def test_real_output_excludes_forbidden_data(monkeypatch, operation, forbidden):
    result, _ = real(monkeypatch, operation)
    assert forbidden not in result.stdout.lower()


@pytest.mark.parametrize("operation", ["check_disk_information", "check_disk_space"])
def test_real_raw_shape(monkeypatch, operation):
    result, _ = real(monkeypatch, operation)
    assert result.state == LocalExecutionState.SUCCESS and result.exit_code == 0
    assert result.command_id == "command-1" and result.stderr == "" and result.errors == ()
    assert result.started_at_monotonic == result.finished_at_monotonic == 10
    assert not result.timed_out and not result.cancelled
    assert len(result.output_chunks) == 1 and result.output_chunks[0].sequence == 0


def test_default_drive_is_safe_and_deterministic(monkeypatch):
    monkeypatch.setattr(LocalDiskInformationAdapter, "_system_drive", staticmethod(lambda: "E:"))
    result, calls = real(monkeypatch, value=None)
    assert json.loads(result.stdout)["drive"] == "E:" and calls == ["E:\\"]


def test_sanitize_valid_result_and_output_bytes(monkeypatch):
    raw, _ = real(monkeypatch)
    sanitized = LocalDiskInformationAdapter().sanitize(raw)
    assert isinstance(sanitized, LocalSanitizedResult)
    assert sanitized.output_bytes == len(sanitized.stdout_summary.encode()) + len(sanitized.stderr_summary.encode())
    assert not sanitized.truncated and sanitized.metadata == {"sanitized": True}


def test_sanitize_truncates_utf8_safely():
    raw = LocalRawExecutionResult(
        command_id="command-1", state=LocalExecutionState.SUCCESS,
        started_at_monotonic=1, finished_at_monotonic=1, exit_code=0,
        stdout="áéíóú" * 20, stderr="erro", output_chunks=(), timed_out=False,
        cancelled=False, metadata={"max_output_bytes": 17},
    )
    result = LocalDiskInformationAdapter().sanitize(raw)
    result.stdout_summary.encode("utf-8").decode("utf-8")
    assert result.truncated and result.output_bytes <= 17


def test_sanitize_redacts_arbitrary_windows_path():
    raw = LocalRawExecutionResult(
        command_id="command-1", state=LocalExecutionState.FAILED,
        started_at_monotonic=1, finished_at_monotonic=1, exit_code=None,
        stdout="", stderr=r"failure at C:\\Users\\Private\\secret.txt", output_chunks=(),
        timed_out=False, cancelled=False, metadata={"redact_sensitive_output": True},
    )
    result = LocalDiskInformationAdapter().sanitize(raw)
    assert "Private" not in result.stderr_summary and "[REDACTED_PATH]" in result.stderr_summary
    assert result.redactions[0].reason == RedactionReason.PERSONAL_DATA


def test_sanitize_does_not_read_disk(monkeypatch):
    raw, _ = real(monkeypatch)
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_disk_information_adapter.shutil.disk_usage",
        lambda target: (_ for _ in ()).throw(AssertionError("sanitize must not collect")),
    )
    assert LocalDiskInformationAdapter().sanitize(raw).state == LocalExecutionState.SUCCESS


def test_sanitize_is_deterministic(monkeypatch):
    raw, _ = real(monkeypatch); adapter = LocalDiskInformationAdapter()
    assert adapter.sanitize(raw) == adapter.sanitize(raw)


@pytest.mark.parametrize("invalid", [None, object(), "raw", 1])
def test_sanitize_rejects_wrong_type(invalid):
    with pytest.raises(ValueError, match="raw_result"):
        LocalDiskInformationAdapter().sanitize(invalid)


@pytest.mark.parametrize("operation,message", [
    ("check_disk_information", "Falha ao coletar informações de disco."),
    ("check_disk_space", "Falha ao consultar espaço em disco."),
])
def test_collection_exception_returns_generic_failure(monkeypatch, operation, message):
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_disk_information_adapter.shutil.disk_usage",
        lambda target: (_ for _ in ()).throw(RuntimeError(r"C:\\Users\\Private\\sensitive")),
    )
    result = LocalDiskInformationAdapter().execute(contract(operation, value="C:", dry_run=False), 10)
    assert result.state == LocalExecutionState.FAILED and result.exit_code is None
    assert result.stderr == result.errors[0] == message and "Private" not in result.stderr
    assert result.stdout == "" and result.output_chunks == ()


def test_non_windows_host_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_disk_information_adapter.platform.system",
        lambda: "Linux",
    )
    result = LocalDiskInformationAdapter().execute(contract(value="C:", dry_run=False), 10)
    assert result.state == LocalExecutionState.FAILED


@pytest.mark.parametrize("subject", ["contract", "operation", "command", "arguments", "sandbox"])
def test_execute_does_not_mutate_input(subject):
    item = contract(value="C:")
    selected = {
        "contract": item, "operation": item.operation, "command": item.command,
        "arguments": item.command.arguments, "sandbox": item.sandbox_policy,
    }[subject]
    before = deepcopy(selected); LocalDiskInformationAdapter().execute(item, 10)
    assert selected == before


def test_raw_and_sanitized_results_are_frozen(monkeypatch):
    raw, _ = real(monkeypatch); sanitized = LocalDiskInformationAdapter().sanitize(raw)
    with pytest.raises(FrozenInstanceError): raw.stdout = "changed"
    with pytest.raises(FrozenInstanceError): sanitized.stdout_summary = "changed"


def test_public_import():
    from app.services.diagnostic_engine import LocalDiskInformationAdapter as PublicAdapter
    assert PublicAdapter is LocalDiskInformationAdapter


@pytest.mark.parametrize("name", [
    "subprocess", "socket", "requests", "httpx", "psutil", "pathlib", "winreg",
])
def test_adapter_has_no_forbidden_imports(name):
    tree = ast.parse(ADAPTER_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


def test_adapter_only_uses_allowed_external_collection_call():
    tree = ast.parse(ADAPTER_FILE.read_text(encoding="utf-8"))
    calls = {
        (node.func.value.id, node.func.attr) for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }
    forbidden = {
        ("os", "system"), ("subprocess", "run"), ("subprocess", "Popen"),
        ("socket", "socket"), ("requests", "get"), ("httpx", "get"),
    }
    assert not calls & forbidden and ("shutil", "disk_usage") in calls


@pytest.mark.parametrize("text", [
    "powershell.exe", "cmd.exe", "wmic.exe", "diskpart.exe", "chkdsk.exe",
    "fsutil.exe", "smartctl.exe", "crystaldiskinfo", "shell=true",
])
def test_adapter_has_no_forbidden_invocations(text):
    assert text not in ADAPTER_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("path", [ADAPTER_FILE, PACKAGE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
