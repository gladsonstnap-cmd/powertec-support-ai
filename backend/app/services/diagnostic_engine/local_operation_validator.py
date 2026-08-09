"""Fail-closed validator from authorized executor contracts to local contracts."""

from copy import deepcopy
from dataclasses import dataclass

from app.services.diagnostic_engine.approval_models import ApprovedActionGrant
from app.services.diagnostic_engine.execution_models import ExecutionAction
from app.services.diagnostic_engine.executor_models import ExecutorRequest, ExecutorStatus
from app.services.diagnostic_engine.local_executor_models import (
    AllowedLocalOperation,
    LocalExecutionCommand,
    LocalExecutionContract,
    LocalOperationArgument,
    LocalOperationType,
)
from app.services.diagnostic_engine.local_executor_policy import DiagnosticLocalExecutorPolicy
from app.services.diagnostic_engine.local_operation_catalog import SafeLocalOperationCatalog


@dataclass(frozen=True)
class LocalOperationValidationResult:
    success: bool = False
    contract: LocalExecutionContract | None = None
    operation: AllowedLocalOperation | None = None
    command: LocalExecutionCommand | None = None
    reasoning: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise ValueError("success must be a boolean")
        if self.success and (self.contract is None or self.operation is None or self.command is None):
            raise ValueError("success=True requires contract, operation, and command")
        expected = (
            ("contract", self.contract, LocalExecutionContract),
            ("operation", self.operation, AllowedLocalOperation),
            ("command", self.command, LocalExecutionCommand),
        )
        for name, value, model_type in expected:
            if value is not None and not isinstance(value, model_type):
                raise ValueError(f"{name} must be a {model_type.__name__}")
        object.__setattr__(self, "contract", deepcopy(self.contract))
        object.__setattr__(self, "operation", deepcopy(self.operation))
        object.__setattr__(self, "command", deepcopy(self.command))
        object.__setattr__(self, "reasoning", tuple(deepcopy(self.reasoning)))
        object.__setattr__(self, "errors", tuple(deepcopy(self.errors)))


class SafeLocalOperationValidator:
    """Validate and build structure only; no local operation is ever executed."""

    _FORBIDDEN_ARGUMENT_NAMES = frozenset(
        {
            "command", "command_line", "script", "shell", "powershell", "cmd",
            "executable", "executable_path", "environment",
        }
    )
    _FORBIDDEN_STRING_FRAGMENTS = ("&&", "||", "$(", "`", ";", "|")

    def __init__(
        self,
        catalog: SafeLocalOperationCatalog | None = None,
        policy: DiagnosticLocalExecutorPolicy | None = None,
    ) -> None:
        if catalog is not None and not isinstance(catalog, SafeLocalOperationCatalog):
            raise ValueError("catalog must be a SafeLocalOperationCatalog")
        if policy is not None and not isinstance(policy, DiagnosticLocalExecutorPolicy):
            raise ValueError("policy must be a DiagnosticLocalExecutorPolicy")
        self.catalog = catalog if catalog is not None else SafeLocalOperationCatalog()
        self.policy = policy if policy is not None else DiagnosticLocalExecutorPolicy()

    def build_contract(
        self,
        *,
        executor_request: ExecutorRequest,
        execution_action: ExecutionAction,
        grant: ApprovedActionGrant,
        operation_name: str,
        arguments: tuple[LocalOperationArgument, ...] = (),
        command_id: str,
        contract_id: str,
        created_at_monotonic: float,
        timeout_seconds: int | None = None,
        dry_run: bool = True,
    ) -> LocalOperationValidationResult:
        model_error = self._model_error(executor_request, execution_action, grant)
        if model_error:
            return self._failure(model_error)
        try:
            operation = self.catalog.get(operation_name)
        except Exception as exc:
            return self._failure(f"Catalog validation failed closed: {type(exc).__name__}: {exc}")
        if operation is None:
            return self._failure(f"Operation {operation_name!r} is not present in the safe allowlist.")
        error = self._request_error(executor_request, execution_action, grant, created_at_monotonic)
        if error:
            return self._failure(error, operation=operation)
        if execution_action.action_name != operation.operation_name:
            return self._failure("ExecutionAction.action_name does not exactly match the catalog operation.", operation)
        try:
            error = self._operation_error(execution_action, operation)
        except Exception as exc:
            return self._failure(
                f"Policy validation failed closed: {type(exc).__name__}: {exc}", operation
            )
        if error:
            return self._failure(error, operation)
        try:
            error = self._argument_error(execution_action, operation, arguments)
        except Exception as exc:
            return self._failure(
                f"Argument policy validation failed closed: {type(exc).__name__}: {exc}", operation
            )
        if error:
            return self._failure(error, operation)

        timeout = (
            min(operation.default_timeout_seconds, self.policy.default_timeout_seconds)
            if timeout_seconds is None
            else timeout_seconds
        )
        try:
            sandbox = self.policy.build_sandbox_policy()
            timeout_valid = self._valid_timeout(
                timeout, executor_request, execution_action, operation, sandbox.max_runtime_seconds
            )
        except Exception as exc:
            return self._failure(
                f"Policy limit validation failed closed: {type(exc).__name__}: {exc}", operation
            )
        if not timeout_valid:
            return self._failure("timeout_seconds is outside the approved structural limits.", operation)
        if not isinstance(dry_run, bool):
            return self._failure("dry_run must be a boolean.", operation)
        if dry_run:
            if not self.policy.allow_dry_run or not operation.supports_dry_run:
                return self._failure("The policy or operation blocks dry-run contracts.", operation)
        else:
            try:
                real_allowed = self.policy.can_execute_real_operation(
                    adapter_type=operation.adapter_type,
                    target=execution_action.target,
                    risk=execution_action.risk,
                    operation_type=operation.operation_type,
                )
            except Exception as exc:
                return self._failure(
                    f"Real-operation policy validation failed closed: {type(exc).__name__}: {exc}",
                    operation,
                )
            if not real_allowed:
                return self._failure("The policy blocks a non-dry-run local contract.", operation)

        try:
            command = self.catalog.build_command(
                operation.operation_name,
                command_id=command_id,
                arguments=arguments,
                dry_run=dry_run,
                timeout_seconds=timeout,
            )
            contract = self.catalog.build_contract(
                contract_id=contract_id,
                executor_request_id=executor_request.request_id,
                execution_plan_id=executor_request.context.execution_plan_id,
                action_id=execution_action.action_id,
                grant_id=grant.grant_id,
                operation_name=operation.operation_name,
                command_id=command_id,
                arguments=arguments,
                dry_run=dry_run,
                timeout_seconds=timeout,
                sandbox_policy=sandbox,
                created_at_monotonic=created_at_monotonic,
            )
        except (TypeError, ValueError) as exc:
            return self._failure(str(exc), operation)
        return LocalOperationValidationResult(
            success=True,
            contract=contract,
            operation=operation,
            command=command,
            reasoning=(
                f"Operation {operation.operation_name} is present in the safe allowlist.",
                f"Target {execution_action.target.value} matches the approved contract.",
                "The contract is structural only; no local operation was executed.",
            ),
        )

    def _model_error(self, request: object, action: object, grant: object) -> str | None:
        if not isinstance(request, ExecutorRequest):
            return "executor_request must be an ExecutorRequest."
        if not isinstance(action, ExecutionAction):
            return "execution_action must be an ExecutionAction."
        if not isinstance(grant, ApprovedActionGrant):
            return "grant must be an ApprovedActionGrant."
        return None

    def _request_error(
        self,
        request: ExecutorRequest,
        action: ExecutionAction,
        grant: ApprovedActionGrant,
        now: float,
    ) -> str | None:
        if request.status not in {ExecutorStatus.PENDING, ExecutorStatus.VALIDATING, ExecutorStatus.AUTHORIZED}:
            return "ExecutorRequest status is not structurally compatible."
        context = request.context
        correlations = (
            (context.action_id, action.action_id, "action_id"),
            (context.action_id, grant.action_id, "grant action_id"),
            (context.execution_plan_id, grant.execution_plan_id, "execution_plan_id"),
            (context.grant_id, grant.grant_id, "grant_id"),
            (context.approval_id, grant.approval_id, "approval_id"),
        )
        for expected, actual, name in correlations:
            if expected != actual:
                return f"The {name} does not match the ExecutorRequest context."
        if request.action_snapshot != action:
            return "ExecutorRequest action snapshot does not match ExecutionAction."
        if request.grant_snapshot != grant:
            return "ExecutorRequest grant snapshot does not match the supplied grant."
        if grant.action_snapshot != action:
            return "The grant does not match the approved action snapshot."
        if self.policy.reject_used_grant and grant.used:
            return "The grant was already used."
        if not isinstance(now, int | float) or isinstance(now, bool) or now < 0:
            return "created_at_monotonic must be a non-negative number."
        if self.policy.require_unexpired_grant and grant.expires_at_monotonic is not None and now >= grant.expires_at_monotonic:
            return "The grant expired before contract creation."
        if self.policy.require_session_match:
            bound_session = grant.metadata.get("session_id")
            if not isinstance(bound_session, str) or not bound_session.strip():
                return "The grant has no reliable session_id binding."
            if bound_session != context.session_id:
                return "The grant session_id does not match the ExecutorRequest context."
        return None

    def _operation_error(
        self, action: ExecutionAction, operation: AllowedLocalOperation
    ) -> str | None:
        if action.target not in operation.allowed_targets:
            return "ExecutionAction target does not match the catalog operation."
        if not self.policy.is_target_allowed(action.target):
            return f"The policy blocks target {action.target.value}."
        if action.risk not in operation.allowed_risks:
            return "ExecutionAction risk does not match the catalog operation."
        if not self.policy.is_risk_allowed(action.risk):
            return f"The policy blocks risk {action.risk.value}."
        action_kind = action.metadata.get("action_kind")
        if action_kind != "read_only" or operation.operation_type != LocalOperationType.READ_ONLY:
            return "The explicit action classification is not READ_ONLY."
        if not self.policy.is_operation_type_allowed(operation.operation_type):
            return "The policy blocks the catalog operation type."
        if not self.policy.is_adapter_allowed(operation.adapter_type):
            return f"The policy blocks adapter {operation.adapter_type.value}."
        return None

    def _argument_error(
        self,
        action: ExecutionAction,
        operation: AllowedLocalOperation,
        arguments: object,
    ) -> str | None:
        if not isinstance(arguments, tuple):
            return "arguments must be a tuple."
        if any(not isinstance(item, LocalOperationArgument) for item in arguments):
            return "arguments must contain LocalOperationArgument values."
        if not self.policy.validate_argument_count(len(arguments)):
            return "The argument count exceeds policy limits."
        names = tuple(item.name for item in arguments)
        if len(set(names)) != len(names):
            return "Argument names must be unique."
        for item in arguments:
            if item.name in self._FORBIDDEN_ARGUMENT_NAMES:
                return f"Argument {item.name!r} is prohibited."
            if len(item.name) > self.policy.max_argument_name_length:
                return f"Argument {item.name!r} exceeds the name length limit."
            if item.name not in operation.argument_names:
                return f"Argument {item.name!r} is not allowed by the operation."
            if item.sensitive and self.policy.reject_sensitive_arguments:
                return f"Sensitive argument {item.name!r} is blocked by policy."
            if isinstance(item.value, str):
                if len(item.value) > self.policy.max_string_argument_length:
                    return f"Argument {item.name!r} exceeds the string length limit."
                if any(fragment in item.value for fragment in self._FORBIDDEN_STRING_FRAGMENTS):
                    return f"Argument {item.name!r} contains a prohibited command fragment."
        if any(name not in names for name in operation.required_argument_names):
            return "A required catalog argument is missing."
        action_parameters = {item.key: item.value for item in action.parameters}
        if any(name not in operation.argument_names for name in action_parameters):
            return "ExecutionAction contains a parameter not allowed by the operation."
        supplied = {item.name: item.value for item in arguments}
        if action_parameters != supplied:
            return "Arguments do not exactly match the approved ExecutionAction parameters."
        return None

    def _valid_timeout(
        self,
        timeout: object,
        request: ExecutorRequest,
        action: ExecutionAction,
        operation: AllowedLocalOperation,
        sandbox_max: int,
    ) -> bool:
        return (
            self.policy.validate_timeout(timeout)
            and timeout <= operation.max_timeout_seconds
            and timeout <= request.timeout_seconds
            and timeout <= action.timeout_seconds
            and timeout <= sandbox_max
        )

    @staticmethod
    def _failure(
        message: str, operation: AllowedLocalOperation | None = None
    ) -> LocalOperationValidationResult:
        return LocalOperationValidationResult(
            success=False,
            operation=operation,
            reasoning=("Validation failed closed; no local operation was executed.",),
            errors=(message,),
        )
