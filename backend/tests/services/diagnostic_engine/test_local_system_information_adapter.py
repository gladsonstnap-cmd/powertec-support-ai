import ast
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import LocalSystemInformationAdapter
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalExecutionState, LocalOperationArgument, LocalOperationType,
    LocalRawExecutionResult, LocalSandboxPolicy, LocalSanitizedResult, RedactionReason,
)
from app.services.diagnostic_engine.local_operation_catalog import SafeLocalOperationCatalog


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ADAPTER_FILE = ROOT / "app/services/diagnostic_engine/local_system_information_adapter.py"
PACKAGE = ADAPTER_FILE.with_name("__init__.py")


def contract(*, dry_run=True, sandbox=None, timeout=30):
    return SafeLocalOperationCatalog().build_contract(
        contract_id="contract-1", executor_request_id="executor-1", execution_plan_id="plan-1",
        action_id="action-1", grant_id="grant-1", operation_name="read_system_information",
        command_id="command-1", dry_run=dry_run, timeout_seconds=timeout,
        sandbox_policy=sandbox,
    )


def windows(monkeypatch, *, hostname="WORKSTATION-01"):
    values = {
        "system": "Windows", "release": "11", "version": "10.0.1", "machine": "AMD64",
        "processor": "Safe CPU", "python_version": "3.12.1", "node": hostname,
    }
    for name, value in values.items():
        monkeypatch.setattr(
            f"app.services.diagnostic_engine.local_system_information_adapter.platform.{name}",
            lambda selected=value: selected,
        )
    monkeypatch.setattr("app.services.diagnostic_engine.local_system_information_adapter.sys.platform", "win32")
    monkeypatch.setattr("app.services.diagnostic_engine.local_system_information_adapter.os.cpu_count", lambda: 8)


def execute_real(monkeypatch, *, sandbox=None):
    windows(monkeypatch)
    return LocalSystemInformationAdapter().execute(contract(dry_run=False, sandbox=sandbox), 10.0)


def test_constructor_and_public_methods():
    item = LocalSystemInformationAdapter()
    assert callable(item.execute) and callable(item.sanitize)
    assert item.operation_name == "read_system_information"


def test_valid_dry_run_contract():
    result = LocalSystemInformationAdapter().execute(contract(), 10)
    assert result.state == LocalExecutionState.SUCCESS and result.exit_code == 0


@pytest.mark.parametrize("invalid", [None, object(), "contract", 1])
def test_invalid_contract_fails_closed(invalid):
    result = LocalSystemInformationAdapter().execute(invalid, 10)
    assert result.state == LocalExecutionState.FAILED and result.exit_code is None


@pytest.mark.parametrize("field_name", ["operation", "command"])
@pytest.mark.parametrize("value", ["other_operation", "ping_host"])
def test_wrong_operation_is_rejected(field_name, value):
    item = contract(); object.__setattr__(getattr(item, field_name), "operation_name", value)
    assert LocalSystemInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("adapter", [LocalAdapterType.PROCESS, LocalAdapterType.UNKNOWN, LocalAdapterType.WINDOWS_SERVICE])
def test_wrong_adapter_is_rejected(adapter):
    item = contract(); object.__setattr__(item.command, "adapter_type", adapter)
    assert LocalSystemInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("target", [ExecutionTarget.NETWORK, ExecutionTarget.LINUX, ExecutionTarget.UNKNOWN])
def test_wrong_target_is_rejected(target):
    item = contract(); object.__setattr__(item.command, "target", target)
    assert LocalSystemInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("risk", [ExecutionRisk.MEDIUM, ExecutionRisk.HIGH, ExecutionRisk.CRITICAL])
def test_wrong_risk_is_rejected(risk):
    item = contract(); object.__setattr__(item.command, "risk", risk)
    assert LocalSystemInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("operation_type", [LocalOperationType.STATE_CHANGING, LocalOperationType.DESTRUCTIVE])
def test_wrong_operation_type_is_rejected(operation_type):
    item = contract(); object.__setattr__(item.command, "operation_type", operation_type)
    assert LocalSystemInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("state", [
    LocalExecutionState.BLOCKED, LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS,
    LocalExecutionState.FAILED, LocalExecutionState.CANCELLED, LocalExecutionState.TIMED_OUT,
])
def test_incompatible_contract_state_is_rejected(state):
    item = contract(); object.__setattr__(item, "state", state)
    assert LocalSystemInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("state", [LocalExecutionState.PENDING, LocalExecutionState.VALIDATED, LocalExecutionState.READY])
def test_structural_contract_states_are_accepted(state):
    item = contract(); object.__setattr__(item, "state", state)
    assert LocalSystemInformationAdapter().execute(item, 10).state == LocalExecutionState.SUCCESS


def test_unexpected_argument_is_rejected():
    item = contract(); object.__setattr__(item.command, "arguments", (LocalOperationArgument("extra", "x"),))
    assert LocalSystemInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("timeout", [0, -1, 31, True, "30"])
def test_invalid_timeout_is_rejected(timeout):
    item = contract(); object.__setattr__(item.command, "timeout_seconds", timeout)
    assert LocalSystemInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("field_name", [
    "allow_shell", "allow_arbitrary_command", "allow_environment_inheritance",
    "allow_network_access", "allow_filesystem_write", "allow_registry_write",
    "allow_service_state_change", "allow_process_termination", "allow_elevation",
    "allow_child_processes",
])
def test_incompatible_sandbox_capability_is_rejected(field_name):
    sandbox = replace(LocalSandboxPolicy(), **{field_name: True})
    item = contract(sandbox=sandbox)
    assert LocalSystemInformationAdapter().execute(item, 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("invalid", [-1, True, "10", None])
def test_invalid_monotonic_time_is_controlled(invalid):
    result = LocalSystemInformationAdapter().execute(contract(), invalid)
    assert result.state == LocalExecutionState.FAILED and result.started_at_monotonic is None


@pytest.mark.parametrize("function", ["system", "release", "version", "machine", "processor", "python_version", "node"])
def test_dry_run_does_not_collect_platform_information(monkeypatch, function):
    def fail():
        raise AssertionError("collection must not run")
    monkeypatch.setattr(f"app.services.diagnostic_engine.local_system_information_adapter.platform.{function}", fail)
    assert LocalSystemInformationAdapter().execute(contract(), 10).state == LocalExecutionState.SUCCESS


def test_dry_run_does_not_collect_cpu_count(monkeypatch):
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_system_information_adapter.os.cpu_count",
        lambda: (_ for _ in ()).throw(AssertionError("collection must not run")),
    )
    assert LocalSystemInformationAdapter().execute(contract(), 10).state == LocalExecutionState.SUCCESS


def test_dry_run_exact_message_and_raw_shape():
    result = LocalSystemInformationAdapter().execute(contract(), 10)
    assert result.stdout == "Dry-run: read_system_information validada; nenhuma coleta real realizada."
    assert result.command_id == "command-1"
    assert result.started_at_monotonic == result.finished_at_monotonic == 10
    assert result.stderr == "" and not result.timed_out and not result.cancelled
    assert len(result.output_chunks) == 1 and result.output_chunks[0].content == result.stdout


def test_real_read_collects_allowed_fields(monkeypatch):
    data = json.loads(execute_real(monkeypatch).stdout)
    assert data == {
        "architecture": "AMD64", "cpu_count": 8, "operating_system": "Windows",
        "operating_system_release": "11", "operating_system_version": "10.0.1",
        "processor": "Safe CPU", "python_platform": "win32", "python_version": "3.12.1",
    }


@pytest.mark.parametrize("key", [
    "operating_system", "operating_system_release", "operating_system_version", "architecture",
    "processor", "python_version", "python_platform", "cpu_count",
])
def test_each_allowed_real_field_is_present(monkeypatch, key):
    assert key in json.loads(execute_real(monkeypatch).stdout)


@pytest.mark.parametrize("forbidden", [
    "username", "home", "environment", "token", "ip", "mac", "serial", "product_key",
    "registry", "credential", "domain", "logged_user",
])
def test_real_output_excludes_forbidden_data(monkeypatch, forbidden):
    output = execute_real(monkeypatch).stdout.lower()
    assert forbidden not in output


def test_real_json_is_compact_sorted_and_deterministic(monkeypatch):
    first = execute_real(monkeypatch); second = execute_real(monkeypatch)
    assert first == second
    assert first.stdout == json.dumps(json.loads(first.stdout), sort_keys=True, separators=(",", ":"))


def test_real_raw_shape(monkeypatch):
    result = execute_real(monkeypatch)
    assert result.state == LocalExecutionState.SUCCESS and result.exit_code == 0
    assert result.command_id == "command-1" and result.stderr == ""
    assert result.started_at_monotonic == result.finished_at_monotonic == 10
    assert not result.timed_out and not result.cancelled
    assert len(result.output_chunks) == 1 and result.output_chunks[0].sequence == 0


def test_hostname_is_omitted_from_raw_by_default(monkeypatch):
    assert "hostname" not in json.loads(execute_real(monkeypatch).stdout)


def test_hostname_is_collected_only_when_raw_preservation_is_explicit(monkeypatch):
    sandbox = LocalSandboxPolicy(preserve_raw_output=True)
    assert json.loads(execute_real(monkeypatch, sandbox=sandbox).stdout)["hostname"] == "WORKSTATION-01"


def test_sanitize_redacts_explicit_hostname(monkeypatch):
    sandbox = LocalSandboxPolicy(preserve_raw_output=True)
    sanitized = LocalSystemInformationAdapter().sanitize(execute_real(monkeypatch, sandbox=sandbox))
    assert "WORKSTATION-01" not in sanitized.stdout_summary
    assert "[REDACTED_HOSTNAME]" in sanitized.stdout_summary
    assert sanitized.redactions[0].reason == RedactionReason.PERSONAL_DATA


def test_sanitize_valid_result_and_output_bytes(monkeypatch):
    sanitized = LocalSystemInformationAdapter().sanitize(execute_real(monkeypatch))
    assert isinstance(sanitized, LocalSanitizedResult)
    assert sanitized.output_bytes == len(sanitized.stdout_summary.encode()) + len(sanitized.stderr_summary.encode())
    assert not sanitized.truncated and sanitized.metadata == {"sanitized": True}


def test_sanitize_truncates_to_contract_limit(monkeypatch):
    sandbox = LocalSandboxPolicy(max_output_bytes=32, max_stderr_bytes=16, max_runtime_seconds=30)
    sanitized = LocalSystemInformationAdapter().sanitize(execute_real(monkeypatch, sandbox=sandbox))
    assert sanitized.truncated and sanitized.output_bytes <= 32


def test_sanitize_does_not_recollect_system(monkeypatch):
    raw = execute_real(monkeypatch)
    monkeypatch.setattr(
        "app.services.diagnostic_engine.local_system_information_adapter.platform.system",
        lambda: (_ for _ in ()).throw(AssertionError("sanitize must not collect")),
    )
    assert LocalSystemInformationAdapter().sanitize(raw).state == LocalExecutionState.SUCCESS


def test_sanitize_is_deterministic(monkeypatch):
    raw = execute_real(monkeypatch); adapter = LocalSystemInformationAdapter()
    assert adapter.sanitize(raw) == adapter.sanitize(raw)


@pytest.mark.parametrize("invalid", [None, object(), "raw", 1])
def test_sanitize_rejects_wrong_type(invalid):
    with pytest.raises(ValueError, match="raw_result"):
        LocalSystemInformationAdapter().sanitize(invalid)


@pytest.mark.parametrize("function", ["system", "release", "version", "machine", "processor", "python_version"])
def test_collection_exception_returns_generic_failure(monkeypatch, function):
    windows(monkeypatch)
    monkeypatch.setattr(
        f"app.services.diagnostic_engine.local_system_information_adapter.platform.{function}",
        lambda: (_ for _ in ()).throw(RuntimeError("sensitive stack detail")),
    )
    result = LocalSystemInformationAdapter().execute(contract(dry_run=False), 10)
    assert result.state == LocalExecutionState.FAILED and result.exit_code is None
    assert result.stderr == result.errors[0] == "Falha ao coletar informações do sistema."
    assert "sensitive" not in result.stderr and result.stdout == ""


def test_non_windows_host_fails_closed(monkeypatch):
    monkeypatch.setattr("app.services.diagnostic_engine.local_system_information_adapter.platform.system", lambda: "Linux")
    assert LocalSystemInformationAdapter().execute(contract(dry_run=False), 10).state == LocalExecutionState.FAILED


@pytest.mark.parametrize("subject", ["contract", "command"])
def test_execute_does_not_mutate_input(subject):
    item = contract(); selected = item if subject == "contract" else item.command; before = deepcopy(selected)
    LocalSystemInformationAdapter().execute(item, 10)
    assert selected == before


def test_raw_and_sanitized_results_are_frozen(monkeypatch):
    raw = execute_real(monkeypatch); sanitized = LocalSystemInformationAdapter().sanitize(raw)
    with pytest.raises(FrozenInstanceError): raw.stdout = "changed"
    with pytest.raises(FrozenInstanceError): sanitized.stdout_summary = "changed"


def test_public_import():
    from app.services.diagnostic_engine import LocalSystemInformationAdapter as PublicAdapter
    assert PublicAdapter is LocalSystemInformationAdapter


@pytest.mark.parametrize("name", ["subprocess", "socket", "requests", "httpx", "psutil", "pathlib"])
def test_adapter_has_no_forbidden_imports(name):
    tree = ast.parse(ADAPTER_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


def test_adapter_has_no_forbidden_calls():
    tree = ast.parse(ADAPTER_FILE.read_text(encoding="utf-8"))
    calls = {
        (node.func.value.id, node.func.attr) for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }
    assert not calls & {
        ("os", "system"), ("subprocess", "Popen"), ("subprocess", "run"),
        ("socket", "socket"), ("requests", "get"), ("httpx", "get"),
    }


@pytest.mark.parametrize("text", ["powershell", "cmd.exe", "wmic", "shell=true", "createprocess"])
def test_adapter_has_no_forbidden_invocations(text):
    assert text not in ADAPTER_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("path", [ADAPTER_FILE, PACKAGE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
