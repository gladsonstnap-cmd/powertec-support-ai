import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import LocalOperationValidationResult, SafeLocalOperationValidator
from app.services.diagnostic_engine.approval_models import ApprovalActor, ApprovalType, ApprovedActionGrant
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction, ExecutionParameter, ExecutionRisk, ExecutionStatus, ExecutionTarget,
)
from app.services.diagnostic_engine.executor_models import ExecutionContext, ExecutorRequest, ExecutorStatus
from app.services.diagnostic_engine.local_executor_models import (
    AllowedLocalOperation, LocalAdapterType, LocalExecutionState, LocalOperationArgument,
    LocalOperationType,
)
from app.services.diagnostic_engine.local_executor_policy import DiagnosticLocalExecutorPolicy
from app.services.diagnostic_engine.local_operation_catalog import SafeLocalOperationCatalog


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
VALIDATOR_FILE = ROOT / "app/services/diagnostic_engine/local_operation_validator.py"
PACKAGE = VALIDATOR_FILE.with_name("__init__.py")


SPECS = {
    "read_system_information": (ExecutionTarget.WINDOWS, ()),
    "list_windows_services": (ExecutionTarget.WINDOWS, ()),
    "check_service_status": (ExecutionTarget.WINDOWS, ("service_name",)),
    "collect_event_logs": (ExecutionTarget.WINDOWS, ("log_name",)),
    "list_processes": (ExecutionTarget.WINDOWS, ()),
    "read_system_process_information": (ExecutionTarget.WINDOWS, ("process_name",)),
    "check_disk_information": (ExecutionTarget.WINDOWS, ()),
    "check_disk_space": (ExecutionTarget.WINDOWS, ()),
    "check_network_configuration": (ExecutionTarget.NETWORK, ()),
    "ping_host": (ExecutionTarget.NETWORK, ("host",)),
    "check_port": (ExecutionTarget.NETWORK, ("host", "port")),
    "validate_configuration": (ExecutionTarget.WINDOWS, ("configuration_name",)),
}


def parameters(name):
    return tuple(
        ExecutionParameter(key=key, value=f"value-{key}", required=True, description="Approved value")
        for key in SPECS[name][1]
    )


def arguments(name):
    return tuple(
        LocalOperationArgument(name=key, value=f"value-{key}", required=True, sensitive=False)
        for key in SPECS[name][1]
    )


def action(name="read_system_information", **changes):
    values = dict(
        action_id="action-1", action_name=name, title="Safe local operation",
        description="Structural action; nothing is executed.", target=SPECS.get(name, (ExecutionTarget.WINDOWS, ()))[0],
        status=ExecutionStatus.READY, risk=ExecutionRisk.LOW, parameters=parameters(name) if name in SPECS else (),
        timeout_seconds=30, requires_confirmation=False, requires_human=False,
        metadata={"action_kind": "read_only"},
    )
    values.update(changes)
    return ExecutionAction(**values)


def grant(item=None, **changes):
    item = item or action()
    values = dict(
        grant_id="grant-1", approval_id="approval-1", execution_plan_id="plan-1",
        action_id=item.action_id, action_snapshot=item,
        approved_by=ApprovalActor("actor-1", ApprovalType.HUMAN_TECHNICIAN),
        approved_at_monotonic=1.0, expires_at_monotonic=100.0,
        metadata={"session_id": "session-1"},
    )
    values.update(changes)
    return ApprovedActionGrant(**values)


def request(item=None, grant_item=None, **changes):
    item = item or action(); grant_item = grant_item or grant(item)
    context = ExecutionContext(
        session_id="session-1", diagnostic_plan_id="diagnostic-1", execution_plan_id="plan-1",
        action_id=item.action_id, grant_id=grant_item.grant_id, approval_id=grant_item.approval_id,
        target=item.target, risk=item.risk, requested_at_monotonic=2.0,
    )
    values = dict(
        request_id="executor-1", context=context, action_snapshot=item,
        grant_snapshot=grant_item, timeout_seconds=30, dry_run=True,
    )
    values.update(changes)
    return ExecutorRequest(**values)


def inputs(name="read_system_information"):
    item = action(name); item_grant = grant(item)
    return item, item_grant, request(item, item_grant)


def build(name="read_system_information", validator=None, **changes):
    item, item_grant, item_request = inputs(name)
    values = dict(
        executor_request=item_request, execution_action=item, grant=item_grant,
        operation_name=name, arguments=arguments(name), command_id="command-1",
        contract_id="contract-1", created_at_monotonic=10.0,
    )
    values.update(changes)
    return (validator or SafeLocalOperationValidator()).build_contract(**values)


def permissive_service_validator():
    policy = replace(DiagnosticLocalExecutorPolicy(), allow_windows_service_adapter=True)
    return SafeLocalOperationValidator(policy=policy)


def test_default_constructor_dependencies():
    item = SafeLocalOperationValidator()
    assert isinstance(item.catalog, SafeLocalOperationCatalog)
    assert isinstance(item.policy, DiagnosticLocalExecutorPolicy)


def test_custom_constructor_dependencies():
    catalog = SafeLocalOperationCatalog(); policy = DiagnosticLocalExecutorPolicy()
    item = SafeLocalOperationValidator(catalog, policy)
    assert item.catalog is catalog and item.policy is policy


@pytest.mark.parametrize(("field_name", "value"), [("catalog", object()), ("policy", object())])
def test_constructor_rejects_wrong_dependency_types(field_name, value):
    with pytest.raises(ValueError, match=field_name):
        SafeLocalOperationValidator(**{field_name: value})


def test_validation_result_is_frozen():
    with pytest.raises(FrozenInstanceError):
        LocalOperationValidationResult().success = True


@pytest.mark.parametrize("name", SPECS)
def test_exact_action_mapping_for_every_catalog_operation(name):
    validator = permissive_service_validator() if name in {"list_windows_services", "check_service_status"} else None
    result = build(name, validator)
    assert result.success and result.operation.operation_name == name


@pytest.mark.parametrize("name", ["missing", "READ_SYSTEM_INFORMATION", "read_system", "ping", "unknown"])
def test_unknown_operation_fails_without_fallback(name):
    result = build(operation_name=name)
    assert not result.success and result.contract is None and result.command is None


@pytest.mark.parametrize("wrong_name", ["ping_host", "check_port", "list_processes"])
def test_action_name_mismatch_fails_closed(wrong_name):
    item, item_grant, item_request = inputs()
    result = SafeLocalOperationValidator().build_contract(
        executor_request=item_request, execution_action=item, grant=item_grant,
        operation_name=wrong_name, arguments=(), command_id="command-1",
        contract_id="contract-1", created_at_monotonic=10,
    )
    assert not result.success


@pytest.mark.parametrize("model_name", ["executor_request", "execution_action", "grant"])
def test_missing_or_wrong_models_are_controlled(model_name):
    result = build(**{model_name: None})
    assert not result.success and model_name.split("execution_")[-1] in result.errors[0]


@pytest.mark.parametrize(
    ("attribute", "value", "fragment"),
    [
        ("action_id", "other", "action_id"),
        ("execution_plan_id", "other", "execution_plan_id"),
        ("grant_id", "other", "grant_id"),
        ("approval_id", "other", "approval_id"),
    ],
)
def test_request_context_correlations(attribute, value, fragment):
    item, item_grant, item_request = inputs(); object.__setattr__(item_request.context, attribute, value)
    result = build(executor_request=item_request, execution_action=item, grant=item_grant)
    assert not result.success and fragment in result.errors[0]


def test_request_action_snapshot_mismatch():
    item, item_grant, item_request = inputs(); object.__setattr__(item_request, "action_snapshot", action(title="changed"))
    assert not build(executor_request=item_request, execution_action=item, grant=item_grant).success


def test_request_grant_snapshot_mismatch():
    item, item_grant, item_request = inputs(); object.__setattr__(item_request.grant_snapshot, "used", True)
    assert not build(executor_request=item_request, execution_action=item, grant=item_grant).success


@pytest.mark.parametrize("status", [ExecutorStatus.BLOCKED, ExecutorStatus.RUNNING, ExecutorStatus.SUCCESS, ExecutorStatus.FAILED, ExecutorStatus.CANCELLED])
def test_incompatible_request_status_is_blocked(status):
    item, item_grant, item_request = inputs(); object.__setattr__(item_request, "status", status)
    assert not build(executor_request=item_request, execution_action=item, grant=item_grant).success


@pytest.mark.parametrize("status", [ExecutorStatus.PENDING, ExecutorStatus.VALIDATING, ExecutorStatus.AUTHORIZED])
def test_structural_request_status_is_accepted(status):
    item, item_grant, item_request = inputs(); object.__setattr__(item_request, "status", status)
    assert build(executor_request=item_request, execution_action=item, grant=item_grant).success


@pytest.mark.parametrize("changes", [{"used": True}, {"expires_at_monotonic": 10.0}, {"expires_at_monotonic": 9.0}])
def test_used_or_expired_grant_is_blocked(changes):
    item = action(); item_grant = grant(item, **changes); item_request = request(item, item_grant)
    assert not build(execution_action=item, grant=item_grant, executor_request=item_request).success


@pytest.mark.parametrize("attribute", ["action_id", "execution_plan_id", "approval_id", "grant_id"])
def test_supplied_grant_identifier_mismatch_is_blocked(attribute):
    item, item_grant, item_request = inputs(); changed = deepcopy(item_grant); object.__setattr__(changed, attribute, "other")
    assert not build(execution_action=item, grant=changed, executor_request=item_request).success


def test_grant_action_snapshot_mismatch_is_blocked():
    item, item_grant, item_request = inputs(); changed = deepcopy(item_grant)
    object.__setattr__(changed, "action_snapshot", action(title="changed"))
    object.__setattr__(item_request, "grant_snapshot", changed)
    assert not build(execution_action=item, grant=changed, executor_request=item_request).success


@pytest.mark.parametrize("metadata", [{}, {"session_id": ""}, {"session_id": "other"}])
def test_session_binding_is_required_and_must_match(metadata):
    item = action(); item_grant = grant(item, metadata=metadata); item_request = request(item, item_grant)
    assert not build(execution_action=item, grant=item_grant, executor_request=item_request).success


def test_custom_policy_can_disable_session_binding_requirement():
    item = action(); item_grant = grant(item, metadata={}); item_request = request(item, item_grant)
    policy = replace(DiagnosticLocalExecutorPolicy(), require_session_match=False)
    result = build(
        validator=SafeLocalOperationValidator(policy=policy), execution_action=item,
        grant=item_grant, executor_request=item_request,
    )
    assert result.success


@pytest.mark.parametrize("target", [ExecutionTarget.NETWORK, ExecutionTarget.LINUX, ExecutionTarget.UNKNOWN])
def test_action_target_mismatch_is_blocked(target):
    item = action(target=target); item_grant = grant(item); item_request = request(item, item_grant)
    assert not build(execution_action=item, grant=item_grant, executor_request=item_request).success


def test_policy_blocked_target_is_rejected():
    policy = replace(DiagnosticLocalExecutorPolicy(), allow_windows_target=False)
    assert not build(validator=SafeLocalOperationValidator(policy=policy)).success


@pytest.mark.parametrize("risk", [ExecutionRisk.MEDIUM, ExecutionRisk.HIGH, ExecutionRisk.CRITICAL])
def test_incompatible_or_blocked_risk_is_rejected(risk):
    item = action(risk=risk); item_grant = grant(item); item_request = request(item, item_grant)
    assert not build(execution_action=item, grant=item_grant, executor_request=item_request).success


@pytest.mark.parametrize("kind", ["state_changing", "destructive", "unknown", None])
def test_non_read_only_classification_is_rejected(kind):
    item = action(metadata={"action_kind": kind}); item_grant = grant(item); item_request = request(item, item_grant)
    assert not build(execution_action=item, grant=item_grant, executor_request=item_request).success


@pytest.mark.parametrize("name", ["read_system_information", "collect_event_logs", "list_processes", "check_disk_space", "ping_host"])
def test_default_allowed_adapters(name):
    assert build(name).success


@pytest.mark.parametrize("name", ["list_windows_services", "check_service_status"])
def test_windows_service_adapter_is_blocked_by_default(name):
    assert not build(name).success


def test_unknown_adapter_from_custom_catalog_is_blocked():
    class UnknownCatalog(SafeLocalOperationCatalog):
        def get(self, operation_name):
            base = super().get("read_system_information")
            return replace(base, operation_name=operation_name, adapter_type=LocalAdapterType.UNKNOWN)

    assert not build(validator=SafeLocalOperationValidator(catalog=UnknownCatalog())).success


def test_policy_error_fails_closed():
    class RaisingPolicy(DiagnosticLocalExecutorPolicy):
        def is_adapter_allowed(self, adapter_type):
            raise RuntimeError("unexpected policy failure")

    result = build(validator=SafeLocalOperationValidator(policy=RaisingPolicy()))
    assert not result.success and "RuntimeError" in result.errors[0]


@pytest.mark.parametrize("name", [name for name, spec in SPECS.items() if spec[1]])
def test_required_arguments_are_accepted(name):
    validator = permissive_service_validator() if name == "check_service_status" else None
    assert build(name, validator).success


@pytest.mark.parametrize("name", [name for name, spec in SPECS.items() if spec[1]])
def test_missing_required_argument_is_rejected(name):
    validator = permissive_service_validator() if name == "check_service_status" else None
    assert not build(name, validator, arguments=()).success


def test_extra_argument_is_rejected():
    assert not build(arguments=(LocalOperationArgument("extra", "x"),)).success


def test_duplicate_argument_is_rejected():
    item = LocalOperationArgument("host", "value-host")
    assert not build("ping_host", arguments=(item, item)).success


def test_arguments_must_be_tuple():
    assert not build(arguments=[]).success


def test_sensitive_argument_is_rejected():
    assert not build("ping_host", arguments=(LocalOperationArgument("host", "x", sensitive=True),)).success


def test_argument_count_limit_is_enforced():
    policy = replace(DiagnosticLocalExecutorPolicy(), max_arguments_per_command=1)
    assert not build("check_port", SafeLocalOperationValidator(policy=policy)).success


def test_argument_name_length_limit_is_enforced():
    policy = replace(DiagnosticLocalExecutorPolicy(), max_argument_name_length=3)
    assert not build("ping_host", SafeLocalOperationValidator(policy=policy)).success


def test_string_argument_length_limit_is_enforced():
    item = action("ping_host", parameters=(ExecutionParameter("host", "long", True, "value"),))
    item_grant = grant(item); item_request = request(item, item_grant)
    policy = replace(DiagnosticLocalExecutorPolicy(), max_string_argument_length=3)
    result = build(
        "ping_host", SafeLocalOperationValidator(policy=policy), execution_action=item,
        grant=item_grant, executor_request=item_request,
        arguments=(LocalOperationArgument("host", "long"),),
    )
    assert not result.success


@pytest.mark.parametrize("name", ["command", "command_line", "script", "shell", "powershell", "cmd", "executable", "executable_path", "environment"])
def test_forbidden_argument_names_are_rejected(name):
    assert not build(arguments=(LocalOperationArgument(name, "x"),)).success


@pytest.mark.parametrize("value", ["x && y", "x || y", "$(whoami)", "`whoami`", "x;y", "x |> y"])
def test_command_fragments_are_rejected(value):
    item = action("ping_host", parameters=(ExecutionParameter("host", value, True, "value"),))
    item_grant = grant(item); item_request = request(item, item_grant)
    result = build(
        "ping_host", execution_action=item, grant=item_grant, executor_request=item_request,
        arguments=(LocalOperationArgument("host", value),),
    )
    assert not result.success


def test_action_parameter_and_argument_value_must_match():
    assert not build("ping_host", arguments=(LocalOperationArgument("host", "different"),)).success


def test_unknown_action_parameter_is_rejected():
    item = action(parameters=(ExecutionParameter("extra", "x", True, "value"),))
    item_grant = grant(item); item_request = request(item, item_grant)
    assert not build(execution_action=item, grant=item_grant, executor_request=item_request).success


def test_action_metadata_is_not_copied_to_contract():
    result = build()
    assert result.success and result.contract.metadata == {} and result.command.metadata == {}


@pytest.mark.parametrize(("timeout", "expected"), [(None, 30), (1, 1), (10, 10), (30, 30)])
def test_timeout_valid(timeout, expected):
    result = build(timeout_seconds=timeout)
    assert result.success and result.contract.command.timeout_seconds == expected


@pytest.mark.parametrize("timeout", [0, -1, 31, 61, True, "30"])
def test_timeout_invalid(timeout):
    assert not build(timeout_seconds=timeout).success


def test_timeout_must_respect_request_and_action():
    item, item_grant, item_request = inputs(); object.__setattr__(item_request, "timeout_seconds", 5)
    assert not build(execution_action=item, grant=item_grant, executor_request=item_request, timeout_seconds=10).success


def test_dry_run_true_is_supported():
    assert build(dry_run=True).success


@pytest.mark.parametrize("dry_run", [False, None, 0, 1, "false"])
def test_non_dry_run_or_invalid_flag_is_blocked_by_default(dry_run):
    assert not build(dry_run=dry_run).success


def test_custom_policy_can_build_non_dry_run_structure_only():
    policy = replace(DiagnosticLocalExecutorPolicy(), allow_local_execution=True, allow_real_execution=True)
    result = build(validator=SafeLocalOperationValidator(policy=policy), dry_run=False)
    assert result.success and not result.contract.command.dry_run


def test_sandbox_is_derived_from_policy():
    policy = replace(
        DiagnosticLocalExecutorPolicy(), max_output_bytes=1000, max_stdout_bytes=900,
        max_stderr_bytes=100, max_output_chunk_bytes=500, max_timeout_seconds=30,
    )
    result = build(validator=SafeLocalOperationValidator(policy=policy))
    assert result.contract.sandbox_policy == policy.build_sandbox_policy()


@pytest.mark.parametrize("field_name", ["allow_shell", "allow_network_access", "allow_filesystem_write", "allow_elevation"])
def test_default_sandbox_capability_remains_disabled(field_name):
    assert not getattr(build().contract.sandbox_policy, field_name)


def test_command_and_contract_fields_come_from_catalog():
    result = build("ping_host")
    command = result.command; contract = result.contract
    assert command.adapter_type == LocalAdapterType.NETWORK_DIAGNOSTIC
    assert command.target == ExecutionTarget.NETWORK and command.risk == ExecutionRisk.LOW
    assert command.operation_type == LocalOperationType.READ_ONLY
    assert contract.operation == result.operation and contract.command == command


def test_contract_preserves_explicit_ids_and_timestamp():
    result = build(command_id="cmd-explicit", contract_id="contract-explicit", created_at_monotonic=12.5)
    contract = result.contract
    assert contract.contract_id == "contract-explicit" and contract.command.command_id == "cmd-explicit"
    assert contract.executor_request_id == "executor-1" and contract.execution_plan_id == "plan-1"
    assert contract.action_id == "action-1" and contract.grant_id == "grant-1"
    assert contract.created_at_monotonic == 12.5 and contract.state == LocalExecutionState.PENDING


@pytest.mark.parametrize("created", [-1, True, "10", None])
def test_invalid_created_timestamp_is_controlled(created):
    assert not build(created_at_monotonic=created).success


@pytest.mark.parametrize("subject", ["request", "action", "grant", "catalog", "policy"])
def test_inputs_are_not_mutated(subject):
    item, item_grant, item_request = inputs(); validator = SafeLocalOperationValidator()
    selected = {"request": item_request, "action": item, "grant": item_grant, "catalog": validator.catalog, "policy": validator.policy}[subject]
    before = deepcopy(selected); validator.build_contract(
        executor_request=item_request, execution_action=item, grant=item_grant,
        operation_name="read_system_information", command_id="command-1",
        contract_id="contract-1", created_at_monotonic=10,
    )
    assert selected == before and item_grant.used is False


def test_same_input_produces_same_result():
    assert build() == build()


def test_success_reasoning_is_operational_only():
    result = build()
    assert result.reasoning and all(isinstance(item, str) for item in result.reasoning)
    assert "no local operation was executed" in result.reasoning[-1]


def test_public_imports():
    from app.services.diagnostic_engine import LocalOperationValidationResult as PublicResult
    from app.services.diagnostic_engine import SafeLocalOperationValidator as PublicValidator
    assert PublicResult is LocalOperationValidationResult and PublicValidator is SafeLocalOperationValidator


@pytest.mark.parametrize("name", ["subprocess", "os", "socket", "requests", "httpx", "pathlib"])
def test_validator_has_no_operational_imports(name):
    tree = ast.parse(VALIDATOR_FILE.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


def test_validator_has_no_execution_or_grant_consumption_methods():
    names = {node.name for node in ast.walk(ast.parse(VALIDATOR_FILE.read_text(encoding="utf-8"))) if isinstance(node, ast.FunctionDef)}
    assert not names & {"execute", "run", "spawn", "consume_grant", "rollback"}


@pytest.mark.parametrize("path", [VALIDATOR_FILE, PACKAGE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes(); assert not content.startswith(b"\xef\xbb\xbf"); content.decode("utf-8")
