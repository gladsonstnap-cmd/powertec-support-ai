import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import SafeLocalOperationCatalog
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    AllowedLocalOperation, LocalAdapterType, LocalExecutionCommand, LocalExecutionContract,
    LocalExecutionState, LocalOperationArgument, LocalOperationType, LocalSandboxPolicy,
)
from app.services.diagnostic_engine.local_executor_policy import DiagnosticLocalExecutorPolicy


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
CATALOG_FILE = ROOT / "app/services/diagnostic_engine/local_operation_catalog.py"
PACKAGE = CATALOG_FILE.with_name("__init__.py")


SPECS = {
    "read_system_information": (LocalAdapterType.SYSTEM_INFORMATION, ExecutionTarget.WINDOWS, (), ()),
    "list_windows_services": (LocalAdapterType.WINDOWS_SERVICE, ExecutionTarget.WINDOWS, ("name_filter",), ()),
    "check_service_status": (LocalAdapterType.WINDOWS_SERVICE, ExecutionTarget.WINDOWS, ("service_name",), ("service_name",)),
    "collect_event_logs": (LocalAdapterType.WINDOWS_EVENT_LOG, ExecutionTarget.WINDOWS, ("log_name", "hours"), ("log_name",)),
    "list_processes": (LocalAdapterType.PROCESS, ExecutionTarget.WINDOWS, ("name_filter",), ()),
    "read_system_process_information": (LocalAdapterType.PROCESS, ExecutionTarget.WINDOWS, ("process_name",), ("process_name",)),
    "check_disk_information": (LocalAdapterType.DISK_INFORMATION, ExecutionTarget.WINDOWS, ("disk_name",), ()),
    "check_disk_space": (LocalAdapterType.DISK_INFORMATION, ExecutionTarget.WINDOWS, ("drive",), ()),
    "check_network_configuration": (LocalAdapterType.NETWORK_DIAGNOSTIC, ExecutionTarget.NETWORK, (), ()),
    "ping_host": (LocalAdapterType.NETWORK_DIAGNOSTIC, ExecutionTarget.NETWORK, ("host",), ("host",)),
    "check_port": (LocalAdapterType.NETWORK_DIAGNOSTIC, ExecutionTarget.NETWORK, ("host", "port"), ("host", "port")),
    "validate_configuration": (LocalAdapterType.SYSTEM_INFORMATION, ExecutionTarget.WINDOWS, ("configuration_name",), ("configuration_name",)),
}


def argument(name, value="value"):
    return LocalOperationArgument(name=name, value=value, required=True, sensitive=False)


def command_arguments(name):
    return tuple(argument(item) for item in SPECS[name][3])


def contract_kwargs(name="read_system_information"):
    return dict(
        contract_id="contract-1", executor_request_id="executor-1", execution_plan_id="plan-1",
        action_id="action-1", grant_id="grant-1", operation_name=name, command_id="command-1",
        arguments=command_arguments(name),
    )


def test_catalog_construction_and_determinism():
    assert SafeLocalOperationCatalog() == SafeLocalOperationCatalog()
    assert SafeLocalOperationCatalog().list_operations() == SafeLocalOperationCatalog().list_operations()


def test_catalog_is_frozen():
    with pytest.raises(FrozenInstanceError):
        SafeLocalOperationCatalog()._operations = ()


def test_names_are_unique_and_sorted():
    names = SafeLocalOperationCatalog().names()
    assert len(names) == len(set(names)) == 12
    assert names == tuple(sorted(names))


def test_list_operations_is_a_tuple_and_defensive():
    catalog = SafeLocalOperationCatalog(); first = catalog.list_operations(); second = catalog.list_operations()
    assert isinstance(first, tuple) and first == second and first is not second
    assert first[0] is not second[0]


@pytest.mark.parametrize("name", SPECS)
def test_each_expected_operation_exists(name):
    assert SafeLocalOperationCatalog().contains(name)


@pytest.mark.parametrize("name", SPECS)
def test_operation_adapter_and_target(name):
    operation = SafeLocalOperationCatalog().require(name)
    assert operation.adapter_type == SPECS[name][0]
    assert operation.allowed_targets == (SPECS[name][1],)


@pytest.mark.parametrize("name", SPECS)
def test_operation_argument_names_and_required_subset(name):
    operation = SafeLocalOperationCatalog().require(name)
    assert operation.argument_names == SPECS[name][2]
    assert operation.required_argument_names == SPECS[name][3]
    assert set(operation.required_argument_names) <= set(operation.argument_names)


@pytest.mark.parametrize("name", SPECS)
def test_operations_have_safe_common_contract(name):
    operation = SafeLocalOperationCatalog().require(name)
    assert operation.operation_type == LocalOperationType.READ_ONLY
    assert operation.allowed_risks == (ExecutionRisk.LOW,)
    assert operation.default_timeout_seconds == operation.max_timeout_seconds == 30
    assert operation.requires_grant and operation.supports_dry_run
    assert not operation.requires_confirmation and not operation.requires_human
    assert not operation.supports_rollback


@pytest.mark.parametrize("name", SPECS)
def test_operations_have_no_arbitrary_argument_names(name):
    forbidden = {"command", "command_line", "script", "executable", "executable_path", "shell", "powershell", "cmd", "environment"}
    assert not forbidden.intersection(SafeLocalOperationCatalog().require(name).argument_names)


def test_catalog_has_no_unknown_or_dangerous_operation():
    operations = SafeLocalOperationCatalog().list_operations()
    assert all(item.adapter_type != LocalAdapterType.UNKNOWN for item in operations)
    assert all(ExecutionTarget.UNKNOWN not in item.allowed_targets for item in operations)
    assert all(item.operation_type not in {LocalOperationType.STATE_CHANGING, LocalOperationType.DESTRUCTIVE} for item in operations)


@pytest.mark.parametrize("name", ["read_system_information", "ping_host", "check_port"])
def test_get_and_require_existing(name):
    catalog = SafeLocalOperationCatalog()
    assert catalog.get(name) == catalog.require(name)


@pytest.mark.parametrize("name", ["missing", "", "PING_HOST", "ping", "unknown"])
def test_get_unknown_returns_none_without_inference(name):
    assert SafeLocalOperationCatalog().get(name) is None


@pytest.mark.parametrize("name", ["missing", "", "PING_HOST", None, 1])
def test_require_unknown_fails_closed(name):
    with pytest.raises(ValueError, match="Unknown"):
        SafeLocalOperationCatalog().require(name)


@pytest.mark.parametrize("name", ["ping_host", "missing"])
def test_contains(name):
    assert SafeLocalOperationCatalog().contains(name) is (name == "ping_host")


@pytest.mark.parametrize(
    ("adapter", "expected"),
    [
        (LocalAdapterType.SYSTEM_INFORMATION, {"read_system_information", "validate_configuration"}),
        (LocalAdapterType.WINDOWS_SERVICE, {"list_windows_services", "check_service_status"}),
        (LocalAdapterType.WINDOWS_EVENT_LOG, {"collect_event_logs"}),
        (LocalAdapterType.PROCESS, {"list_processes", "read_system_process_information"}),
        (LocalAdapterType.NETWORK_DIAGNOSTIC, {"check_network_configuration", "ping_host", "check_port"}),
        (LocalAdapterType.DISK_INFORMATION, {"check_disk_information", "check_disk_space"}),
        (LocalAdapterType.FILE_INFORMATION, set()),
        (LocalAdapterType.UNKNOWN, set()),
    ],
)
def test_find_by_adapter(adapter, expected):
    assert {item.operation_name for item in SafeLocalOperationCatalog().find_by_adapter(adapter)} == expected


@pytest.mark.parametrize(
    ("target", "count"),
    [(ExecutionTarget.WINDOWS, 9), (ExecutionTarget.NETWORK, 3), (ExecutionTarget.LINUX, 0), (ExecutionTarget.UNKNOWN, 0)],
)
def test_find_by_target(target, count):
    assert len(SafeLocalOperationCatalog().find_by_target(target)) == count


@pytest.mark.parametrize(
    ("risk", "count"),
    [(ExecutionRisk.LOW, 12), (ExecutionRisk.MEDIUM, 0), (ExecutionRisk.HIGH, 0), (ExecutionRisk.CRITICAL, 0)],
)
def test_find_by_risk(risk, count):
    assert len(SafeLocalOperationCatalog().find_by_risk(risk)) == count


@pytest.mark.parametrize(
    ("operation_type", "count"),
    [(LocalOperationType.READ_ONLY, 12), (LocalOperationType.STATE_CHANGING, 0), (LocalOperationType.DESTRUCTIVE, 0)],
)
def test_find_by_operation_type(operation_type, count):
    assert len(SafeLocalOperationCatalog().find_by_operation_type(operation_type)) == count


@pytest.mark.parametrize(
    ("method", "invalid"),
    [
        ("find_by_adapter", "SYSTEM_INFORMATION"), ("find_by_adapter", 1),
        ("find_by_target", "WINDOWS"), ("find_by_target", 1),
        ("find_by_risk", "LOW"), ("find_by_risk", 1),
        ("find_by_operation_type", "READ_ONLY"), ("find_by_operation_type", 1),
    ],
)
def test_filters_reject_wrong_types(method, invalid):
    with pytest.raises(ValueError):
        getattr(SafeLocalOperationCatalog(), method)(invalid)


@pytest.mark.parametrize(
    ("name", "allowed"),
    [
        ("read_system_information", True), ("collect_event_logs", True),
        ("list_windows_services", False), ("check_service_status", False),
        ("ping_host", True), ("missing", False),
    ],
)
def test_default_policy_filter(name, allowed):
    assert SafeLocalOperationCatalog().is_allowed_by_policy(name, DiagnosticLocalExecutorPolicy()) is allowed


def test_network_catalog_permission_does_not_enable_operational_network():
    policy = DiagnosticLocalExecutorPolicy()
    assert SafeLocalOperationCatalog().is_allowed_by_policy("ping_host", policy)
    assert not policy.allow_network_access


def test_custom_policy_can_enable_windows_service_catalog_entries():
    policy = replace(DiagnosticLocalExecutorPolicy(), allow_windows_service_adapter=True)
    assert SafeLocalOperationCatalog().is_allowed_by_policy("list_windows_services", policy)


@pytest.mark.parametrize(
    "policy",
    [
        DiagnosticLocalExecutorPolicy(allow_windows_target=False),
        DiagnosticLocalExecutorPolicy(allow_low_risk=False),
        DiagnosticLocalExecutorPolicy(allow_read_only_operations=False),
        DiagnosticLocalExecutorPolicy(max_timeout_seconds=10, default_timeout_seconds=10),
    ],
)
def test_policy_can_block_catalog_operation(policy):
    assert not SafeLocalOperationCatalog().is_allowed_by_policy("read_system_information", policy)


def test_policy_type_is_required():
    with pytest.raises(ValueError, match="policy"):
        SafeLocalOperationCatalog().is_allowed_by_policy("ping_host", object())


@pytest.mark.parametrize("name", SPECS)
def test_build_command_for_each_operation(name):
    item = SafeLocalOperationCatalog().build_command(name, command_id="command-1", arguments=command_arguments(name))
    assert isinstance(item, LocalExecutionCommand)
    assert item.operation_name == name
    assert item.adapter_type == SPECS[name][0] and item.target == SPECS[name][1]
    assert item.risk == ExecutionRisk.LOW and item.operation_type == LocalOperationType.READ_ONLY


@pytest.mark.parametrize("invalid", ["", " ", None])
def test_build_command_requires_command_id(invalid):
    with pytest.raises(ValueError, match="command_id"):
        SafeLocalOperationCatalog().build_command("read_system_information", command_id=invalid)


@pytest.mark.parametrize("name", ["missing", "PING_HOST", "command", "unknown"])
def test_build_command_rejects_unknown_operation(name):
    with pytest.raises(ValueError, match="Unknown"):
        SafeLocalOperationCatalog().build_command(name, command_id="command-1")


@pytest.mark.parametrize("name", [name for name, spec in SPECS.items() if spec[3]])
def test_build_command_rejects_missing_required_arguments(name):
    with pytest.raises(ValueError, match="missing"):
        SafeLocalOperationCatalog().build_command(name, command_id="command-1")


def test_build_command_rejects_extra_argument():
    with pytest.raises(ValueError, match="not allowed"):
        SafeLocalOperationCatalog().build_command(
            "ping_host", command_id="command-1", arguments=(argument("host"), argument("extra")),
        )


def test_build_command_rejects_duplicate_arguments():
    with pytest.raises(ValueError, match="unique"):
        SafeLocalOperationCatalog().build_command(
            "ping_host", command_id="command-1", arguments=(argument("host"), argument("host")),
        )


def test_build_command_requires_argument_tuple():
    with pytest.raises(ValueError, match="tuple"):
        SafeLocalOperationCatalog().build_command("ping_host", command_id="command-1", arguments=[argument("host")])


@pytest.mark.parametrize(("timeout", "expected"), [(None, 30), (1, 1), (10, 10), (30, 30)])
def test_build_command_timeout(timeout, expected):
    item = SafeLocalOperationCatalog().build_command(
        "read_system_information", command_id="command-1", timeout_seconds=timeout,
    )
    assert item.timeout_seconds == expected


@pytest.mark.parametrize("timeout", [0, -1, 31, True, "30"])
def test_build_command_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="timeout"):
        SafeLocalOperationCatalog().build_command(
            "read_system_information", command_id="command-1", timeout_seconds=timeout,
        )


@pytest.mark.parametrize("dry_run", [True, False])
def test_build_command_preserves_explicit_dry_run(dry_run):
    assert SafeLocalOperationCatalog().build_command(
        "read_system_information", command_id="command-1", dry_run=dry_run,
    ).dry_run is dry_run


def test_build_contract_valid_and_structurally_linked():
    item = SafeLocalOperationCatalog().build_contract(**contract_kwargs("check_port"))
    assert isinstance(item, LocalExecutionContract)
    assert item.operation.operation_name == item.command.operation_name == "check_port"
    assert item.state == LocalExecutionState.PENDING


@pytest.mark.parametrize("field_name", ["contract_id", "executor_request_id", "execution_plan_id", "action_id", "grant_id", "command_id"])
def test_build_contract_requires_ids(field_name):
    values = contract_kwargs(); values[field_name] = ""
    with pytest.raises(ValueError, match=field_name):
        SafeLocalOperationCatalog().build_contract(**values)


def test_build_contract_uses_default_sandbox():
    assert SafeLocalOperationCatalog().build_contract(**contract_kwargs()).sandbox_policy == LocalSandboxPolicy()


def test_build_contract_preserves_custom_sandbox():
    sandbox = LocalSandboxPolicy(max_runtime_seconds=30)
    item = SafeLocalOperationCatalog().build_contract(**contract_kwargs(), sandbox_policy=sandbox)
    assert item.sandbox_policy == sandbox and item.sandbox_policy is not sandbox


@pytest.mark.parametrize("created", [0, 1, 1.5, 100])
def test_build_contract_preserves_monotonic_timestamp(created):
    assert SafeLocalOperationCatalog().build_contract(
        **contract_kwargs(), created_at_monotonic=created,
    ).created_at_monotonic == created


def test_builds_do_not_mutate_catalog():
    catalog = SafeLocalOperationCatalog(); before = deepcopy(catalog.list_operations())
    catalog.build_command("read_system_information", command_id="command-1")
    catalog.build_contract(**contract_kwargs())
    assert catalog.list_operations() == before


def test_returned_operation_cannot_mutate_catalog_metadata():
    catalog = SafeLocalOperationCatalog(); returned = catalog.require("ping_host")
    returned.metadata["local"] = True
    assert catalog.require("ping_host").metadata == {}


def test_public_import():
    from app.services.diagnostic_engine import SafeLocalOperationCatalog as PublicCatalog
    assert PublicCatalog is SafeLocalOperationCatalog


@pytest.mark.parametrize("name", ["subprocess", "os", "socket", "requests", "httpx", "pathlib"])
def test_catalog_has_no_operational_imports(name):
    tree = ast.parse(CATALOG_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


def test_catalog_has_no_execution_or_grant_consumption_methods():
    names = {node.name for node in ast.walk(ast.parse(CATALOG_FILE.read_text(encoding="utf-8"))) if isinstance(node, ast.FunctionDef)}
    assert not names & {"execute", "run", "spawn", "consume_grant", "rollback"}


@pytest.mark.parametrize("path", [CATALOG_FILE, PACKAGE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
