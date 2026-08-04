"""Deterministic, descriptive builder for diagnostic execution plans."""

from copy import deepcopy
from dataclasses import replace
from typing import Sequence

from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction,
    ExecutionParameter,
    ExecutionPlan,
    ExecutionResult,
    ExecutionRisk,
    ExecutionStatus,
    ExecutionTarget,
)
from app.services.diagnostic_engine.execution_policy import DiagnosticExecutionPolicy
from app.services.diagnostic_engine.normalization import normalize_text
from app.services.diagnostic_engine.planner_models import (
    DiagnosticPlan,
    DiagnosticPlanStatus,
    PlanStep,
    PlanStepType,
)


_CRITICAL_TERMS = (
    "formatar", "apagar", "excluir", "deletar", "remover banco", "limpar banco",
    "restaurar fabrica", "firmware", "bios", "destruicao de dados",
)
_HIGH_TERMS = (
    "regedit", "registro do windows", "certificado digital", "certificado fiscal", "nfe",
    "nfce", "sat", "sefaz", "credenciais", "senha", "producao", "banco de dados",
    "firewall", "desativar antivirus",
)
_STATE_TERMS = (
    "reiniciar", "resetar", "alterar", "configurar", "instalar", "atualizar", "parar",
    "iniciar servico", "habilitar", "desabilitar",
)
_READ_ONLY_TERMS = (
    "verificar", "consultar", "conferir", "validar", "listar", "visualizar", "coletar log",
    "ler log", "ping", "status", "espaco em disco", "servicos", "processos",
)
_SECRET_KEYS = ("password", "senha", "token", "secret", "segredo", "credential", "credencial")
_PARAMETER_KEYS = (
    "host", "port", "service_name", "log_name", "hours", "process_name", "path",
    "database_type", "printer_name",
)


class DiagnosticExecutionEngine:
    """Translate diagnostic steps into descriptions; never execute them."""

    def __init__(self, policy: DiagnosticExecutionPolicy | None = None) -> None:
        self.policy = policy if policy is not None else DiagnosticExecutionPolicy()

    def build_execution_plan(
        self,
        diagnostic_plan: DiagnosticPlan | None,
        previous_execution_plan: ExecutionPlan | None = None,
    ) -> ExecutionResult:
        if diagnostic_plan is None:
            return self._failure("diagnostic_plan is required")

        source = deepcopy(diagnostic_plan)
        previous = deepcopy(previous_execution_plan)
        actions: list[ExecutionAction] = []
        reasoning: list[str] = []
        errors: list[str] = []
        risk_counts = {risk: 0 for risk in ExecutionRisk}
        previous_by_step = self._previous_by_step(previous)

        for step in source.steps:
            if len(actions) >= self.policy.max_actions:
                self._append(errors, "The maximum action limit was reached.")
                break
            if step.step_type == PlanStepType.ASK_QUESTION:
                self._append(reasoning, f"Step {step.step_id} requires user input and generated no action.")
                continue
            if step.step_type == PlanStepType.COMPLETE:
                self._append(reasoning, f"Step {step.step_id} completes the diagnostic plan.")
                break

            previous_action = previous_by_step.get(step.step_id) or self._equivalent_previous(previous, step)
            action = self._build_action(step, len(actions) + 1, previous_action)
            if action is None:
                self._append(errors, f"Step {step.step_id} could not be mapped to a safe descriptive action.")
                if self.policy.stop_after_blocked:
                    break
                continue

            if risk_counts[action.risk] >= self.policy.max_actions_for_risk(action.risk):
                action = replace(action, status=ExecutionStatus.BLOCKED)
                self._append(errors, f"Risk limit reached for {action.risk.value} actions.")
            else:
                risk_counts[action.risk] += 1

            actions.append(action)
            if action.status == ExecutionStatus.BLOCKED:
                for error in self._blocking_errors(action, step):
                    if len(errors) < self.policy.max_errors:
                        errors.append(error)
            if action.status == ExecutionStatus.FAILED and self.policy.stop_after_failure:
                self._append(reasoning, f"Stopped after failed action {action.action_id}.")
                break
            if action.status == ExecutionStatus.BLOCKED and self.policy.stop_after_blocked:
                self._append(reasoning, f"Stopped after blocked action {action.action_id}.")
                break
            if step.step_type == PlanStepType.ESCALATE_TO_HUMAN:
                self._append(reasoning, "Human escalation blocks automatic follow-up actions.")
                break

        terminal = self._terminal_ids(actions)
        current = next(
            (item.action_id for item in actions if item.status in {ExecutionStatus.READY, ExecutionStatus.PENDING}),
            None,
        )
        plan_status = self._plan_status(source, actions, errors)
        metadata = self._safe_metadata(source.metadata) if self.policy.preserve_metadata else {}
        metadata["source_diagnostic_plan_id"] = source.plan_id
        plan_id = self._plan_id(source, previous)
        execution_plan = ExecutionPlan(
            plan_id=plan_id,
            status=plan_status,
            actions=tuple(actions),
            current_action_id=current,
            completed_actions=terminal[ExecutionStatus.SUCCESS],
            failed_actions=terminal[ExecutionStatus.FAILED],
            cancelled_actions=terminal[ExecutionStatus.CANCELLED],
            metadata=metadata,
            errors=self._limited(errors),
        )
        selected = next(
            (item for item in execution_plan.actions if item.action_id == current),
            execution_plan.actions[0] if execution_plan.actions else None,
        )
        success = not errors and plan_status not in {ExecutionStatus.BLOCKED, ExecutionStatus.FAILED}
        return ExecutionResult(
            success=success,
            execution_plan=execution_plan,
            selected_action=selected,
            reasoning=self._limited_reasoning(reasoning),
            errors=self._limited(errors),
            metadata=metadata,
        )

    def _build_action(
        self, step: PlanStep, position: int, previous: ExecutionAction | None
    ) -> ExecutionAction | None:
        content = self._content(step)
        action_name = self._action_name(step, content)
        if action_name is None:
            return None
        target = self._target(content)
        risk = self._risk(step, content)
        kind = self._action_kind(content, risk)
        confirmation = step.requires_confirmation or self.policy.requires_confirmation(risk)
        human = step.requires_human or self.policy.requires_human(risk)
        blocked = (
            step.step_type in {PlanStepType.REQUEST_CONFIRMATION, PlanStepType.ESCALATE_TO_HUMAN}
            or confirmation
            or human
            or not self.policy.is_target_allowed(target)
            or not self.policy.is_risk_allowed(risk)
            or not self._kind_allowed(kind)
        )
        status = ExecutionStatus.BLOCKED if blocked else ExecutionStatus.READY
        action_id = f"action-{position:03d}-{action_name.replace('_', '-')}"
        metadata = self._safe_metadata(step.metadata) if self.policy.preserve_metadata else {}
        metadata.update({"source_step_id": step.step_id, "action_kind": kind})
        action = ExecutionAction(
            action_id=action_id,
            action_name=action_name,
            title=step.title,
            description=f"Descriptive action only; no operation was executed. {step.instruction}",
            target=target,
            status=status,
            risk=risk,
            parameters=self._parameters(step),
            timeout_seconds=min(self.policy.default_timeout_seconds, self.policy.max_timeout_seconds),
            requires_confirmation=confirmation,
            requires_human=human,
            metadata=metadata,
        )
        if previous is not None and previous.status in {
            ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED
        }:
            action = replace(action, action_id=previous.action_id, status=previous.status)
        return action

    @staticmethod
    def _content(step: PlanStep) -> str:
        values = (step.title, step.instruction, step.recommended_test, step.recommended_action)
        return normalize_text(" ".join(value for value in values if value))

    @staticmethod
    def _action_name(step: PlanStep, content: str) -> str | None:
        if step.step_type == PlanStepType.VERIFY_RESULT:
            return "verify_result"
        if step.step_type == PlanStepType.REQUEST_CONFIRMATION:
            return "request_confirmation"
        if step.step_type == PlanStepType.RECOMMEND_ACTION:
            return "recommend_manual_action"
        if step.step_type == PlanStepType.ESCALATE_TO_HUMAN:
            return "escalate_to_human"
        mappings = (
            (("event viewer", "event log", "logs de evento", "log de eventos"), "collect_event_logs"),
            (("espaco em disco", "disk space"), "check_disk_space"),
            (("ping",), "ping_host"),
            (("porta", " port "), "check_port"),
            (("dns", "conectividade", "network connectivity"), "check_network_connectivity"),
            (("processo", "processos"), "list_processes"),
            (("impressora", "printer"), "check_printer_status"),
            (("banco", "database"), "check_database_service_status"),
            (("servico", "service"), "check_service_status"),
            (("informacao do sistema", "system information"), "read_system_information"),
            (("configuracao", "configuration"), "validate_configuration"),
        )
        for terms, name in mappings:
            if any(term in content for term in terms):
                return name
        return "validate_configuration" if any(term in content for term in _READ_ONLY_TERMS) else None

    @staticmethod
    def _target(content: str) -> ExecutionTarget:
        if "remote agent" in content or "agente remoto" in content:
            return ExecutionTarget.REMOTE_AGENT
        if "linux" in content:
            return ExecutionTarget.LINUX
        if any(term in content for term in ("ping", "porta", "dns", "conectividade", "rede", "network")):
            return ExecutionTarget.NETWORK
        if any(term in content for term in ("windows", "servico", "service", "event viewer", "processo")):
            return ExecutionTarget.WINDOWS
        return ExecutionTarget.UNKNOWN

    @staticmethod
    def _risk(step: PlanStep, content: str) -> ExecutionRisk:
        if any(term in content for term in _CRITICAL_TERMS):
            return ExecutionRisk.CRITICAL
        if any(term in content for term in _HIGH_TERMS):
            return ExecutionRisk.HIGH
        if any(term in content for term in _STATE_TERMS):
            return ExecutionRisk.MEDIUM
        mapped = {
            RiskLevel.READ_ONLY: ExecutionRisk.LOW,
            RiskLevel.LOW: ExecutionRisk.LOW,
            RiskLevel.MEDIUM: ExecutionRisk.MEDIUM,
            RiskLevel.HIGH: ExecutionRisk.HIGH,
            RiskLevel.CRITICAL: ExecutionRisk.CRITICAL,
        }
        return mapped[step.risk_level]

    @staticmethod
    def _action_kind(content: str, risk: ExecutionRisk) -> str:
        if risk == ExecutionRisk.CRITICAL or any(term in content for term in _CRITICAL_TERMS):
            return "destructive"
        if risk in {ExecutionRisk.MEDIUM, ExecutionRisk.HIGH} or any(term in content for term in _STATE_TERMS):
            return "state_changing"
        return "read_only"

    def _kind_allowed(self, kind: str) -> bool:
        return {
            "read_only": self.policy.allow_read_only_actions,
            "state_changing": self.policy.allow_state_changing_actions,
            "destructive": self.policy.allow_destructive_actions,
        }[kind]

    def _blocking_errors(self, action: ExecutionAction, step: PlanStep) -> tuple[str, ...]:
        errors = []
        if not self.policy.is_target_allowed(action.target):
            errors.append(f"Target {action.target.value} is blocked by execution policy.")
        if not self.policy.is_risk_allowed(action.risk):
            errors.append(f"Risk {action.risk.value} is blocked by execution policy.")
        kind = str(action.metadata["action_kind"])
        if not self._kind_allowed(kind):
            errors.append(f"Action kind {kind} is blocked by execution policy.")
        if action.requires_human:
            errors.append(f"Action {action.action_id} requires human handling.")
        if action.requires_confirmation:
            errors.append(f"Action {action.action_id} requires confirmation.")
        if step.step_type == PlanStepType.ESCALATE_TO_HUMAN:
            errors.append("The diagnostic step explicitly requires human escalation.")
        return tuple(errors)

    def _parameters(self, step: PlanStep) -> tuple[ExecutionParameter, ...]:
        explicit: dict[str, object] = {}
        for key in _PARAMETER_KEYS:
            if key in step.metadata and not self._is_secret(key, step.metadata[key]):
                explicit[key] = deepcopy(step.metadata[key])
        for condition in (*step.preconditions, *step.success_conditions, *step.failure_conditions):
            if condition.key in _PARAMETER_KEYS and not self._is_secret(condition.key, condition.expected_value):
                explicit.setdefault(condition.key, deepcopy(condition.expected_value))
        return tuple(
            ExecutionParameter(key, value, True, f"Explicit parameter: {key}")
            for key, value in list(explicit.items())[: self.policy.max_parameters_per_action]
        )

    @classmethod
    def _safe_metadata(cls, metadata: dict[str, object]) -> dict[str, object]:
        safe: dict[str, object] = {}
        for key, value in deepcopy(dict(metadata)).items():
            if cls._is_secret(str(key), value):
                continue
            if isinstance(value, dict):
                safe[key] = cls._safe_metadata(value)
            else:
                safe[key] = value
        return safe

    @staticmethod
    def _is_secret(key: str, value: object) -> bool:
        normalized_key = normalize_text(key)
        if any(term in normalized_key for term in _SECRET_KEYS):
            return True
        if isinstance(value, str):
            normalized_value = normalize_text(value)
            return any(term in normalized_value for term in ("senha", "password", "token", "secret"))
        return False

    @staticmethod
    def _previous_by_step(previous: ExecutionPlan | None) -> dict[str, ExecutionAction]:
        if previous is None:
            return {}
        return {
            str(action.metadata["source_step_id"]): action
            for action in previous.actions
            if action.metadata.get("source_step_id") is not None
        }

    @classmethod
    def _equivalent_previous(
        cls, previous: ExecutionPlan | None, step: PlanStep
    ) -> ExecutionAction | None:
        if previous is None:
            return None
        name = cls._action_name(step, cls._content(step))
        return next(
            (action for action in previous.actions if action.action_name == name and action.title == step.title),
            None,
        )

    @staticmethod
    def _terminal_ids(actions: Sequence[ExecutionAction]) -> dict[ExecutionStatus, tuple[str, ...]]:
        return {
            status: tuple(action.action_id for action in actions if action.status == status)
            for status in (ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED)
        }

    @staticmethod
    def _plan_status(
        source: DiagnosticPlan, actions: Sequence[ExecutionAction], errors: Sequence[str]
    ) -> ExecutionStatus:
        statuses = {action.status for action in actions}
        if ExecutionStatus.FAILED in statuses:
            return ExecutionStatus.FAILED
        if ExecutionStatus.BLOCKED in statuses or errors:
            return ExecutionStatus.BLOCKED
        if any(status in statuses for status in (ExecutionStatus.READY, ExecutionStatus.PENDING)):
            return ExecutionStatus.READY
        if actions and statuses == {ExecutionStatus.CANCELLED}:
            return ExecutionStatus.CANCELLED
        if source.status == DiagnosticPlanStatus.COMPLETED or actions and statuses == {ExecutionStatus.SUCCESS}:
            return ExecutionStatus.SUCCESS
        return ExecutionStatus.BLOCKED

    @staticmethod
    def _plan_id(source: DiagnosticPlan, previous: ExecutionPlan | None) -> str:
        expected = f"execution-{source.plan_id}"
        if previous is not None and previous.metadata.get("source_diagnostic_plan_id") == source.plan_id:
            return previous.plan_id
        return expected

    def _append(self, messages: list[str], message: str) -> None:
        limit = self.policy.max_errors if "error" in message.lower() else self.policy.max_reasoning_messages
        if len(messages) < limit:
            messages.append(message)

    def _limited(self, messages: Sequence[str]) -> tuple[str, ...]:
        return tuple(messages[: self.policy.max_errors])

    def _limited_reasoning(self, messages: Sequence[str]) -> tuple[str, ...]:
        if not self.policy.preserve_reasoning:
            return ()
        return tuple(messages[: self.policy.max_reasoning_messages])

    def _failure(self, error: str) -> ExecutionResult:
        return ExecutionResult(success=False, errors=(error,)[: self.policy.max_errors])
