import ast
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import DiagnosticLocalExecutorPolicy
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget
from app.services.diagnostic_engine.local_executor_models import (
    LocalAdapterType, LocalOperationType, LocalSandboxPolicy,
)


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
POLICY = ROOT / "app/services/diagnostic_engine/local_executor_policy.py"
PACKAGE = POLICY.with_name("__init__.py")


LIMIT_DEFAULTS = {
    "max_arguments_per_command": 20,
    "max_argument_name_length": 128,
    "max_string_argument_length": 4096,
    "default_timeout_seconds": 30,
    "max_timeout_seconds": 60,
    "max_output_bytes": 1048576,
    "max_stdout_bytes": 786432,
    "max_stderr_bytes": 262144,
    "max_output_chunks": 1000,
    "max_output_chunk_bytes": 65536,
    "max_redactions": 100,
    "max_errors": 20,
    "max_metadata_depth": 8,
    "max_metadata_items": 100,
}

TRUE_DEFAULTS = {
    "allow_dry_run", "require_dry_run_before_real_execution",
    "allow_windows_event_log_adapter", "allow_system_information_adapter",
    "allow_process_adapter", "allow_network_diagnostic_adapter", "allow_disk_information_adapter",
    "allow_windows_target", "allow_network_target", "allow_low_risk",
    "allow_read_only_operations", "require_valid_grant", "require_unexpired_grant",
    "reject_used_grant", "require_action_match", "require_execution_plan_match",
    "require_session_match", "require_confirmation_for_state_change",
    "require_human_for_state_change", "require_administrator_for_destructive",
    "require_sandbox", "require_restricted_environment", "require_output_limits",
    "require_timeout", "require_redaction", "require_audit", "require_structured_operation",
    "reject_unknown_operation", "reject_extra_arguments", "reject_sensitive_arguments",
    "capture_stdout", "capture_stderr", "truncate_oversized_output", "sanitize_output",
    "redact_sensitive_output", "allow_cancellation", "require_confirmation_before_rollback",
    "require_human_before_rollback", "rollback_state_changes_only",
    "fail_closed_on_unknown_adapter", "fail_closed_on_unknown_target",
    "fail_closed_on_unknown_risk", "fail_closed_on_unknown_operation",
    "fail_closed_on_invalid_arguments", "fail_closed_on_sensitive_data",
    "fail_closed_on_missing_grant", "fail_closed_on_policy_error",
}


def test_default_creation_and_field_count():
    item = DiagnosticLocalExecutorPolicy()
    assert len(fields(item)) == 106


def test_custom_creation():
    item = DiagnosticLocalExecutorPolicy(allow_local_execution=True, max_timeout_seconds=120)
    assert item.allow_local_execution and item.max_timeout_seconds == 120


def test_policy_is_frozen():
    with pytest.raises(FrozenInstanceError):
        DiagnosticLocalExecutorPolicy().allow_shell = True


def test_equality_and_repr_are_deterministic():
    first = DiagnosticLocalExecutorPolicy(); second = DiagnosticLocalExecutorPolicy()
    assert first == second and repr(first) == repr(second)


@pytest.mark.parametrize(("field_name", "expected"), LIMIT_DEFAULTS.items())
def test_limit_defaults(field_name, expected):
    assert getattr(DiagnosticLocalExecutorPolicy(), field_name) == expected


@pytest.mark.parametrize("field_name", LIMIT_DEFAULTS)
@pytest.mark.parametrize("invalid", [0, True])
def test_limits_reject_non_positive_and_boolean_values(field_name, invalid):
    with pytest.raises(ValueError, match=field_name):
        DiagnosticLocalExecutorPolicy(**{field_name: invalid})


def test_negative_limit_is_rejected():
    with pytest.raises(ValueError, match="max_errors"):
        DiagnosticLocalExecutorPolicy(max_errors=-1)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"default_timeout_seconds": 61}, "default_timeout_seconds"),
        ({"max_stdout_bytes": 1048577}, "max_stdout_bytes"),
        ({"max_stderr_bytes": 1048577}, "max_stderr_bytes"),
        ({"max_output_chunk_bytes": 1048577}, "max_output_chunk_bytes"),
    ],
)
def test_relational_limits(changes, message):
    with pytest.raises(ValueError, match=message):
        DiagnosticLocalExecutorPolicy(**changes)


def test_all_boolean_defaults_match_fail_closed_contract():
    item = DiagnosticLocalExecutorPolicy()
    bool_names = {entry.name for entry in fields(item)} - set(LIMIT_DEFAULTS)
    assert {name for name in bool_names if getattr(item, name)} == TRUE_DEFAULTS


@pytest.mark.parametrize("field_name", [
    "allow_local_execution", "allow_shell", "allow_network_access", "allow_filesystem_read",
    "allow_registry_write", "require_valid_grant", "require_sandbox", "capture_stdout",
    "allow_cancellation", "fail_closed_on_policy_error",
])
@pytest.mark.parametrize("invalid", [1, 0, "true", None])
def test_boolean_fields_reject_non_boolean_values(field_name, invalid):
    with pytest.raises(ValueError, match=field_name):
        DiagnosticLocalExecutorPolicy(**{field_name: invalid})


@pytest.mark.parametrize(
    ("adapter", "allowed"),
    [
        (LocalAdapterType.WINDOWS_SERVICE, False),
        (LocalAdapterType.WINDOWS_EVENT_LOG, True),
        (LocalAdapterType.SYSTEM_INFORMATION, True),
        (LocalAdapterType.PROCESS, True),
        (LocalAdapterType.NETWORK_DIAGNOSTIC, True),
        (LocalAdapterType.DISK_INFORMATION, True),
        (LocalAdapterType.FILE_INFORMATION, False),
        (LocalAdapterType.UNKNOWN, False),
    ],
)
def test_default_adapter_allowlist(adapter, allowed):
    assert DiagnosticLocalExecutorPolicy().is_adapter_allowed(adapter) is allowed


@pytest.mark.parametrize(
    ("adapter", "flag"),
    [
        (LocalAdapterType.WINDOWS_SERVICE, "allow_windows_service_adapter"),
        (LocalAdapterType.WINDOWS_EVENT_LOG, "allow_windows_event_log_adapter"),
        (LocalAdapterType.SYSTEM_INFORMATION, "allow_system_information_adapter"),
        (LocalAdapterType.PROCESS, "allow_process_adapter"),
        (LocalAdapterType.NETWORK_DIAGNOSTIC, "allow_network_diagnostic_adapter"),
        (LocalAdapterType.DISK_INFORMATION, "allow_disk_information_adapter"),
        (LocalAdapterType.FILE_INFORMATION, "allow_file_information_adapter"),
        (LocalAdapterType.UNKNOWN, "allow_unknown_adapter"),
    ],
)
def test_adapter_flags_are_applied(adapter, flag):
    item = replace(DiagnosticLocalExecutorPolicy(), **{flag: True})
    assert item.is_adapter_allowed(adapter)


@pytest.mark.parametrize(
    ("target", "allowed"),
    [
        (ExecutionTarget.LOCAL_MACHINE, False), (ExecutionTarget.WINDOWS, True),
        (ExecutionTarget.NETWORK, True), (ExecutionTarget.LINUX, False),
        (ExecutionTarget.REMOTE_AGENT, False), (ExecutionTarget.UNKNOWN, False),
    ],
)
def test_default_targets(target, allowed):
    assert DiagnosticLocalExecutorPolicy().is_target_allowed(target) is allowed


@pytest.mark.parametrize(
    ("risk", "allowed"),
    [(ExecutionRisk.LOW, True), (ExecutionRisk.MEDIUM, False), (ExecutionRisk.HIGH, False), (ExecutionRisk.CRITICAL, False)],
)
def test_default_risks(risk, allowed):
    assert DiagnosticLocalExecutorPolicy().is_risk_allowed(risk) is allowed


@pytest.mark.parametrize(
    ("operation_type", "allowed"),
    [(LocalOperationType.READ_ONLY, True), (LocalOperationType.STATE_CHANGING, False), (LocalOperationType.DESTRUCTIVE, False)],
)
def test_default_operation_types(operation_type, allowed):
    assert DiagnosticLocalExecutorPolicy().is_operation_type_allowed(operation_type) is allowed


@pytest.mark.parametrize(
    ("method", "value"),
    [
        ("is_adapter_allowed", "SYSTEM_INFORMATION"), ("is_adapter_allowed", 1),
        ("is_target_allowed", "WINDOWS"), ("is_target_allowed", 1),
        ("is_risk_allowed", "LOW"), ("is_risk_allowed", 1),
        ("is_operation_type_allowed", "READ_ONLY"), ("is_operation_type_allowed", 1),
        ("requires_grant", "READ_ONLY"), ("requires_confirmation", 1), ("requires_human", None),
    ],
)
def test_helpers_reject_wrong_enum_types(method, value):
    with pytest.raises(ValueError):
        getattr(DiagnosticLocalExecutorPolicy(), method)(value)


@pytest.mark.parametrize(
    ("value", "valid"),
    [(1, True), (30, True), (60, True), (0, False), (61, False), (-1, False), (True, False), ("30", False)],
)
def test_validate_timeout(value, valid):
    assert DiagnosticLocalExecutorPolicy().validate_timeout(value) is valid


@pytest.mark.parametrize(
    ("value", "valid"),
    [(0, True), (1, True), (20, True), (21, False), (-1, False), (True, False), ("1", False)],
)
def test_validate_argument_count(value, valid):
    assert DiagnosticLocalExecutorPolicy().validate_argument_count(value) is valid


@pytest.mark.parametrize(
    ("stdout", "stderr", "total", "valid"),
    [
        (0, 0, 0, True), (10, 10, 20, True), (786432, 262144, 1048576, True),
        (786433, 0, 1, False), (0, 262145, 1, False), (0, 0, 1048577, False),
        (-1, 0, 0, False), (True, 0, 0, False),
    ],
)
def test_validate_output_limits(stdout, stderr, total, valid):
    assert DiagnosticLocalExecutorPolicy().validate_output_limits(stdout, stderr, total) is valid


@pytest.mark.parametrize("operation_type", list(LocalOperationType))
def test_requires_grant_for_all_default_operation_types(operation_type):
    assert DiagnosticLocalExecutorPolicy().requires_grant(operation_type)


@pytest.mark.parametrize(
    ("operation_type", "confirmation", "human"),
    [
        (LocalOperationType.READ_ONLY, False, False),
        (LocalOperationType.STATE_CHANGING, True, True),
        (LocalOperationType.DESTRUCTIVE, True, True),
    ],
)
def test_confirmation_and_human_requirements(operation_type, confirmation, human):
    item = DiagnosticLocalExecutorPolicy()
    assert item.requires_confirmation(operation_type) is confirmation
    assert item.requires_human(operation_type) is human


def test_real_execution_is_disabled_by_default():
    item = DiagnosticLocalExecutorPolicy()
    assert not item.allow_local_execution and not item.allow_real_execution
    assert item.allow_dry_run and item.require_dry_run_before_real_execution
    assert not item.can_execute_real_operation(
        adapter_type=LocalAdapterType.SYSTEM_INFORMATION,
        target=ExecutionTarget.WINDOWS,
        risk=ExecutionRisk.LOW,
        operation_type=LocalOperationType.READ_ONLY,
    )


@pytest.mark.parametrize(
    "blocked_change",
    [
        {"allow_local_execution": False}, {"allow_real_execution": False},
        {"allow_system_information_adapter": False}, {"allow_windows_target": False},
        {"allow_low_risk": False}, {"allow_read_only_operations": False},
    ],
)
def test_real_execution_query_requires_every_policy_gate(blocked_change):
    enabled = dict(
        allow_local_execution=True, allow_real_execution=True,
        allow_system_information_adapter=True, allow_windows_target=True,
        allow_low_risk=True, allow_read_only_operations=True,
    )
    enabled.update(blocked_change)
    item = DiagnosticLocalExecutorPolicy(**enabled)
    assert not item.can_execute_real_operation(
        adapter_type=LocalAdapterType.SYSTEM_INFORMATION, target=ExecutionTarget.WINDOWS,
        risk=ExecutionRisk.LOW, operation_type=LocalOperationType.READ_ONLY,
    )


def test_real_execution_query_can_be_enabled_but_executes_nothing():
    item = DiagnosticLocalExecutorPolicy(allow_local_execution=True, allow_real_execution=True)
    assert item.can_execute_real_operation(
        adapter_type=LocalAdapterType.SYSTEM_INFORMATION, target=ExecutionTarget.WINDOWS,
        risk=ExecutionRisk.LOW, operation_type=LocalOperationType.READ_ONLY,
    )


def test_build_sandbox_policy_maps_conservatively():
    source = DiagnosticLocalExecutorPolicy()
    sandbox = source.build_sandbox_policy()
    assert sandbox == LocalSandboxPolicy(
        max_output_bytes=source.max_output_bytes,
        max_stderr_bytes=source.max_stderr_bytes,
        max_runtime_seconds=source.max_timeout_seconds,
    )


@pytest.mark.parametrize(
    ("source_field", "sandbox_field"),
    [
        ("allow_shell", "allow_shell"),
        ("allow_arbitrary_commands", "allow_arbitrary_command"),
        ("allow_environment_inheritance", "allow_environment_inheritance"),
        ("allow_network_access", "allow_network_access"),
        ("allow_filesystem_write", "allow_filesystem_write"),
        ("allow_registry_write", "allow_registry_write"),
        ("allow_service_state_change", "allow_service_state_change"),
        ("allow_process_termination", "allow_process_termination"),
        ("allow_child_processes", "allow_child_processes"),
    ],
)
def test_sandbox_maps_only_explicit_capabilities(source_field, sandbox_field):
    source = DiagnosticLocalExecutorPolicy(**{source_field: True})
    sandbox = source.build_sandbox_policy()
    assert getattr(sandbox, sandbox_field) is True


def test_public_import():
    from app.services.diagnostic_engine import DiagnosticLocalExecutorPolicy as PublicPolicy
    assert PublicPolicy is DiagnosticLocalExecutorPolicy


@pytest.mark.parametrize("name", ["subprocess", "os", "socket", "requests", "httpx", "pathlib"])
def test_policy_has_no_operational_imports(name):
    tree = ast.parse(POLICY.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


def test_policy_has_no_execution_or_grant_consumption_methods():
    names = {node.name for node in ast.walk(ast.parse(POLICY.read_text(encoding="utf-8"))) if isinstance(node, ast.FunctionDef)}
    assert not names & {"execute", "run", "spawn", "consume_grant", "rollback"}


@pytest.mark.parametrize("path", [POLICY, PACKAGE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
