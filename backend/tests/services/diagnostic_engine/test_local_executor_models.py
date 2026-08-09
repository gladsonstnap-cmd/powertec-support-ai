import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    AllowedLocalOperation, LocalAdapterType, LocalExecutionCommand, LocalExecutionContract,
    LocalExecutionState, LocalOperationArgument, LocalOperationType, LocalOutputChunk,
    LocalRawExecutionResult, LocalSandboxPolicy, LocalSanitizedResult, OutputStreamType,
    RedactedValue, RedactionReason,
)
from app.services.diagnostic_engine.execution_models import ExecutionRisk, ExecutionTarget


HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
MODELS = ROOT / "app/services/diagnostic_engine/local_executor_models.py"
PACKAGE = MODELS.with_name("__init__.py")


def argument(**changes):
    values = dict(name="host", value="localhost", required=True, sensitive=False, description="Target host")
    values.update(changes)
    return LocalOperationArgument(**values)


def operation(**changes):
    values = dict(
        operation_name="ping_host", adapter_type=LocalAdapterType.NETWORK_DIAGNOSTIC,
        operation_type=LocalOperationType.READ_ONLY, allowed_targets=(ExecutionTarget.NETWORK,),
        allowed_risks=(ExecutionRisk.LOW,), argument_names=("host",),
        required_argument_names=("host",), default_timeout_seconds=10, max_timeout_seconds=60,
        requires_grant=True, requires_confirmation=False, requires_human=False,
        supports_dry_run=True, supports_cancellation=True, supports_rollback=False,
        description="Structured future network diagnostic.",
    )
    values.update(changes)
    return AllowedLocalOperation(**values)


def command(**changes):
    values = dict(
        command_id="command-1", operation_name="ping_host",
        adapter_type=LocalAdapterType.NETWORK_DIAGNOSTIC, arguments=(argument(),),
        target=ExecutionTarget.NETWORK, risk=ExecutionRisk.LOW,
        operation_type=LocalOperationType.READ_ONLY, timeout_seconds=10, dry_run=True,
    )
    values.update(changes)
    return LocalExecutionCommand(**values)


def chunk(sequence=0, **changes):
    values = dict(
        sequence=sequence, stream=OutputStreamType.STDOUT, content="summary", truncated=False,
        redacted=False, redaction_reasons=(), occurred_at_monotonic=float(sequence),
    )
    values.update(changes)
    return LocalOutputChunk(**values)


def raw(**changes):
    values = dict(
        command_id="command-1", state=LocalExecutionState.PENDING,
        started_at_monotonic=None, finished_at_monotonic=None, exit_code=None,
        stdout="", stderr="", output_chunks=(), timed_out=False, cancelled=False,
    )
    values.update(changes)
    return LocalRawExecutionResult(**values)


def redaction(**changes):
    values = dict(placeholder="[REDACTED]", reason=RedactionReason.SECRET, original_length=8)
    values.update(changes)
    return RedactedValue(**values)


def sanitized(**changes):
    values = dict(
        command_id="command-1", state=LocalExecutionState.PENDING, exit_code=None,
        stdout_summary="", stderr_summary="", redactions=(), truncated=False, output_bytes=0,
    )
    values.update(changes)
    return LocalSanitizedResult(**values)


def contract(**changes):
    values = dict(
        contract_id="contract-1", executor_request_id="executor-1", execution_plan_id="plan-1",
        action_id="action-1", grant_id="grant-1", operation=operation(), command=command(),
        sandbox_policy=LocalSandboxPolicy(), state=LocalExecutionState.PENDING,
        created_at_monotonic=1.0,
    )
    values.update(changes)
    return LocalExecutionContract(**values)


ENUMS = (LocalOperationType, LocalAdapterType, LocalExecutionState, OutputStreamType, RedactionReason)


@pytest.mark.parametrize("enum_type", ENUMS)
def test_enums_are_string_enums(enum_type):
    assert all(isinstance(item, str) and item.name == item.value for item in enum_type)


@pytest.mark.parametrize(
    ("enum_type", "names"),
    [
        (LocalOperationType, ["READ_ONLY", "STATE_CHANGING", "DESTRUCTIVE"]),
        (LocalAdapterType, ["WINDOWS_SERVICE", "WINDOWS_EVENT_LOG", "SYSTEM_INFORMATION", "PROCESS", "NETWORK_DIAGNOSTIC", "DISK_INFORMATION", "FILE_INFORMATION", "UNKNOWN"]),
        (LocalExecutionState, ["PENDING", "VALIDATED", "BLOCKED", "READY", "RUNNING", "SUCCESS", "FAILED", "CANCELLED", "TIMED_OUT"]),
        (OutputStreamType, ["STDOUT", "STDERR", "SYSTEM", "AUDIT"]),
        (RedactionReason, ["PASSWORD", "TOKEN", "SECRET", "CREDENTIAL", "API_KEY", "AUTHORIZATION", "COOKIE", "PRIVATE_KEY", "PERSONAL_DATA", "UNKNOWN"]),
    ],
)
def test_enum_members_are_stable(enum_type, names):
    assert [item.name for item in enum_type] == names


def test_argument_valid_and_value_hidden_from_repr():
    item = argument(value="private-value", sensitive=True)
    assert item.value == "private-value" and "private-value" not in repr(item)


@pytest.mark.parametrize("name", ["", " ", None, 1])
def test_argument_rejects_invalid_name(name):
    with pytest.raises(ValueError, match="name"):
        argument(name=name)


@pytest.mark.parametrize("field_name", ["required", "sensitive"])
@pytest.mark.parametrize("invalid", [None, 1])
def test_argument_rejects_invalid_flags(field_name, invalid):
    with pytest.raises(ValueError, match=field_name):
        argument(**{field_name: invalid})


def test_argument_value_is_defensively_copied():
    value = {"safe": [1]}; item = argument(value=value); value["safe"].append(2)
    assert item.value == {"safe": [1]}


def test_structured_future_operation_names_are_representable():
    names = (
        "read_system_information", "list_windows_services", "check_service_status",
        "collect_event_logs", "list_processes", "check_disk_information", "check_disk_space",
        "ping_host", "check_port", "check_network_configuration",
    )
    assert tuple(operation(operation_name=name).operation_name for name in names) == names


@pytest.mark.parametrize("field_name", ["operation_name", "description"])
@pytest.mark.parametrize("invalid", [""])
def test_operation_rejects_empty_text(field_name, invalid):
    with pytest.raises(ValueError, match=field_name):
        operation(**{field_name: invalid})


@pytest.mark.parametrize("field_name", ["default_timeout_seconds", "max_timeout_seconds"])
@pytest.mark.parametrize("invalid", [0, True])
def test_operation_rejects_invalid_timeout(field_name, invalid):
    with pytest.raises(ValueError, match=field_name):
        operation(**{field_name: invalid})


def test_operation_rejects_default_timeout_above_maximum():
    with pytest.raises(ValueError, match="must not exceed"):
        operation(default_timeout_seconds=61)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("argument_names", ("host", "host")),
        ("required_argument_names", ("host", "host")),
        ("allowed_targets", (ExecutionTarget.NETWORK, ExecutionTarget.NETWORK)),
        ("allowed_risks", (ExecutionRisk.LOW, ExecutionRisk.LOW)),
    ],
)
def test_operation_rejects_duplicates(field_name, value):
    with pytest.raises(ValueError, match="unique"):
        operation(**{field_name: value})


def test_operation_rejects_unknown_required_argument():
    with pytest.raises(ValueError, match="required_argument_names"):
        operation(required_argument_names=("missing",))


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    [
        ("adapter_type", "NETWORK_DIAGNOSTIC"), ("operation_type", "READ_ONLY"),
        ("allowed_targets", ("NETWORK",)), ("allowed_risks", ("LOW",)),
    ],
)
def test_operation_rejects_invalid_contract_types(field_name, invalid):
    with pytest.raises(ValueError, match=field_name):
        operation(**{field_name: invalid})


OPERATION_FLAGS = (
    "requires_grant", "requires_confirmation", "requires_human", "supports_dry_run",
    "supports_cancellation", "supports_rollback",
)


@pytest.mark.parametrize("field_name", OPERATION_FLAGS)
def test_operation_rejects_non_boolean_flags(field_name):
    with pytest.raises(ValueError, match=field_name):
        operation(**{field_name: 1})


def test_sandbox_defaults_are_conservative():
    item = LocalSandboxPolicy()
    assert not any(getattr(item, name) for name in (
        "allow_shell", "allow_arbitrary_command", "allow_environment_inheritance",
        "allow_network_access", "allow_filesystem_write", "allow_registry_write",
        "allow_service_state_change", "allow_process_termination", "allow_elevation",
        "allow_child_processes", "preserve_raw_output",
    ))
    assert item.redact_sensitive_output
    assert (item.max_output_bytes, item.max_stderr_bytes, item.max_runtime_seconds) == (1048576, 262144, 60)


SANDBOX_LIMITS = ("max_output_bytes", "max_stderr_bytes", "max_runtime_seconds")
SANDBOX_FLAGS = tuple(item.name for item in fields(LocalSandboxPolicy) if item.name not in SANDBOX_LIMITS)


@pytest.mark.parametrize("field_name", SANDBOX_LIMITS)
@pytest.mark.parametrize("invalid", [0, True])
def test_sandbox_rejects_invalid_limits(field_name, invalid):
    with pytest.raises(ValueError, match=field_name):
        LocalSandboxPolicy(**{field_name: invalid})


@pytest.mark.parametrize("field_name", SANDBOX_FLAGS)
def test_sandbox_rejects_non_boolean_flags(field_name):
    with pytest.raises(ValueError, match=field_name):
        LocalSandboxPolicy(**{field_name: 1})


def test_command_valid_and_has_no_arbitrary_execution_fields():
    item = command()
    names = {entry.name for entry in fields(item)}
    assert not names & {"command_line", "shell", "shell_command", "script", "executable", "executable_path"}


@pytest.mark.parametrize("field_name", ["command_id", "operation_name"])
@pytest.mark.parametrize("invalid", [""])
def test_command_rejects_empty_ids(field_name, invalid):
    with pytest.raises(ValueError, match=field_name):
        command(**{field_name: invalid})


def test_command_rejects_duplicate_argument_names():
    with pytest.raises(ValueError, match="unique"):
        command(arguments=(argument(), argument()))


@pytest.mark.parametrize("invalid", [0, True])
def test_command_rejects_invalid_timeout(invalid):
    with pytest.raises(ValueError, match="timeout_seconds"):
        command(timeout_seconds=invalid)


@pytest.mark.parametrize("invalid", [None, 1])
def test_command_rejects_invalid_dry_run(invalid):
    with pytest.raises(ValueError, match="dry_run"):
        command(dry_run=invalid)


@pytest.mark.parametrize("invalid", [-1, True])
def test_output_chunk_rejects_invalid_sequence(invalid):
    with pytest.raises(ValueError, match="sequence"):
        chunk(sequence=invalid)


@pytest.mark.parametrize("invalid", [-1, True])
def test_output_chunk_rejects_invalid_timestamp(invalid):
    with pytest.raises(ValueError, match="occurred_at_monotonic"):
        chunk(occurred_at_monotonic=invalid)


@pytest.mark.parametrize("field_name", ["truncated", "redacted"])
def test_output_chunk_rejects_invalid_flags(field_name):
    with pytest.raises(ValueError, match=field_name):
        chunk(**{field_name: 1})


def test_output_chunk_rejects_duplicate_redaction_reasons():
    with pytest.raises(ValueError, match="unique"):
        chunk(redaction_reasons=(RedactionReason.SECRET, RedactionReason.SECRET))


def test_raw_result_valid_and_chunks_are_sorted():
    item = raw(output_chunks=(chunk(2), chunk(0), chunk(1)))
    assert [part.sequence for part in item.output_chunks] == [0, 1, 2]


def test_raw_result_rejects_duplicate_chunk_sequences():
    with pytest.raises(ValueError, match="unique"):
        raw(output_chunks=(chunk(0), chunk(0)))


@pytest.mark.parametrize(
    ("started", "finished"),
    [(2, 1), (1.5, 1.4), (10, 0)],
)
def test_raw_result_rejects_inconsistent_timestamps(started, finished):
    with pytest.raises(ValueError, match="finished"):
        raw(started_at_monotonic=started, finished_at_monotonic=finished)


@pytest.mark.parametrize(
    ("state", "changes"),
    [
        (LocalExecutionState.TIMED_OUT, {}),
        (LocalExecutionState.CANCELLED, {}),
        (LocalExecutionState.SUCCESS, {"exit_code": 1}),
    ],
)
def test_raw_result_rejects_incoherent_terminal_state(state, changes):
    with pytest.raises(ValueError):
        raw(state=state, **changes)


@pytest.mark.parametrize(
    ("state", "changes"),
    [
        (LocalExecutionState.TIMED_OUT, {"timed_out": True}),
        (LocalExecutionState.CANCELLED, {"cancelled": True}),
        (LocalExecutionState.SUCCESS, {"exit_code": 0}),
    ],
)
def test_raw_result_accepts_coherent_terminal_state(state, changes):
    assert raw(state=state, **changes).state == state


def test_redacted_value_never_has_original_value_field():
    item = redaction()
    assert "original_value" not in {entry.name for entry in fields(item)}


@pytest.mark.parametrize("invalid", [""])
def test_redacted_value_rejects_empty_placeholder(invalid):
    with pytest.raises(ValueError, match="placeholder"):
        redaction(placeholder=invalid)


@pytest.mark.parametrize("invalid", [-1, True])
def test_redacted_value_rejects_invalid_original_length(invalid):
    with pytest.raises(ValueError, match="original_length"):
        redaction(original_length=invalid)


def test_sanitized_result_valid():
    assert sanitized(redactions=(redaction(),), output_bytes=10).output_bytes == 10


@pytest.mark.parametrize("invalid", [-1, True])
def test_sanitized_result_rejects_invalid_output_bytes(invalid):
    with pytest.raises(ValueError, match="output_bytes"):
        sanitized(output_bytes=invalid)


@pytest.mark.parametrize("field_name", ["stdout_summary", "stderr_summary"])
def test_sanitized_result_requires_string_summaries(field_name):
    with pytest.raises(ValueError, match="strings"):
        sanitized(**{field_name: None})


def test_contract_valid():
    assert contract().state == LocalExecutionState.PENDING


@pytest.mark.parametrize("field_name", ["contract_id", "executor_request_id", "execution_plan_id", "action_id", "grant_id"])
@pytest.mark.parametrize("invalid", [""])
def test_contract_rejects_empty_ids(field_name, invalid):
    with pytest.raises(ValueError, match=field_name):
        contract(**{field_name: invalid})


@pytest.mark.parametrize(
    ("operation_changes", "command_changes", "message"),
    [
        ({"operation_name": "other"}, {}, "operation_name"),
        ({"adapter_type": LocalAdapterType.SYSTEM_INFORMATION}, {}, "adapter_type"),
        ({"operation_type": LocalOperationType.STATE_CHANGING}, {}, "operation_type"),
        ({"allowed_targets": (ExecutionTarget.WINDOWS,)}, {}, "target"),
        ({"allowed_risks": (ExecutionRisk.MEDIUM,)}, {}, "risk"),
        ({}, {"timeout_seconds": 61}, "operation maximum"),
        ({"argument_names": ("host", "port")}, {"arguments": (argument(name="other"),)}, "not allowed"),
        ({"required_argument_names": ("host",)}, {"arguments": ()}, "missing"),
    ],
)
def test_contract_rejects_incompatible_operation(operation_changes, command_changes, message):
    with pytest.raises(ValueError, match=message):
        contract(operation=operation(**operation_changes), command=command(**command_changes))


def test_contract_rejects_timeout_above_sandbox_limit():
    with pytest.raises(ValueError, match="sandbox maximum"):
        contract(command=command(timeout_seconds=20), sandbox_policy=LocalSandboxPolicy(max_runtime_seconds=10))


@pytest.mark.parametrize("state", [LocalExecutionState.RUNNING, LocalExecutionState.SUCCESS])
def test_contract_rejects_unsafe_initial_states(state):
    with pytest.raises(ValueError, match="initial"):
        contract(state=state)


@pytest.mark.parametrize("state", [
    LocalExecutionState.PENDING, LocalExecutionState.VALIDATED, LocalExecutionState.BLOCKED,
    LocalExecutionState.READY, LocalExecutionState.FAILED, LocalExecutionState.CANCELLED,
    LocalExecutionState.TIMED_OUT,
])
def test_contract_accepts_non_execution_initial_states(state):
    assert contract(state=state).state == state


def test_contract_rejects_unsupported_dry_run():
    with pytest.raises(ValueError, match="dry-run"):
        contract(operation=operation(supports_dry_run=False))


SENSITIVE_KEYS = (
    "password", "senha", "token", "secret", "segredo", "credential", "credencial",
    "api_key", "authorization", "bearer", "cookie", "private_key",
)
MODEL_FACTORIES = (argument, operation, command, chunk, raw, redaction, sanitized, contract)


@pytest.mark.parametrize("key", SENSITIVE_KEYS)
def test_sensitive_metadata_keys_are_rejected(key):
    with pytest.raises(ValueError, match="metadata"):
        argument(metadata={key: "hidden"})


@pytest.mark.parametrize("factory", MODEL_FACTORIES)
def test_nested_sensitive_metadata_is_rejected_for_every_model(factory):
    with pytest.raises(ValueError, match="metadata"):
        factory(metadata={"safe": [{"nested": {"token": "hidden"}}]})


@pytest.mark.parametrize("factory", MODEL_FACTORIES)
def test_metadata_is_defensively_copied(factory):
    metadata = {"safe": [1]}; item = factory(metadata=metadata); metadata["safe"].append(2)
    assert item.metadata == {"safe": [1]}


@pytest.mark.parametrize("factory", MODEL_FACTORIES)
def test_models_are_frozen(factory):
    item = factory()
    with pytest.raises(FrozenInstanceError):
        item.metadata = {}


def test_models_have_deterministic_equality():
    assert contract() == contract()


def test_contract_defensively_copies_nested_contracts():
    source_operation = operation(); source_command = command(); source_policy = LocalSandboxPolicy()
    item = contract(operation=source_operation, command=source_command, sandbox_policy=source_policy)
    assert item.operation == source_operation and item.operation is not source_operation
    assert item.command == source_command and item.command is not source_command
    assert item.sandbox_policy == source_policy and item.sandbox_policy is not source_policy


def test_public_imports_are_available():
    from app.services.diagnostic_engine import LocalExecutionContract as PublicContract
    assert PublicContract is LocalExecutionContract


@pytest.mark.parametrize("name", ["subprocess", "os", "socket", "requests", "httpx", "pathlib"])
def test_models_have_no_operational_imports(name):
    tree = ast.parse(MODELS.read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert name not in imports


@pytest.mark.parametrize("path", [MODELS, PACKAGE, HERE])
def test_sprint_files_are_utf8_without_bom(path):
    content = path.read_bytes()
    assert not content.startswith(b"\xef\xbb\xbf")
    content.decode("utf-8")
