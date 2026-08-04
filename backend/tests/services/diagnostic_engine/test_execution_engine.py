from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.diagnostic_engine import DiagnosticExecutionEngine
from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction,
    ExecutionPlan,
    ExecutionRisk,
    ExecutionStatus,
    ExecutionTarget,
)
from app.services.diagnostic_engine.execution_policy import DiagnosticExecutionPolicy
from app.services.diagnostic_engine.planner_models import (
    DiagnosticPlan,
    DiagnosticPlanStatus,
    PlanCondition,
    PlanStep,
    PlanStepStatus,
    PlanStepType,
)


def step(kind=PlanStepType.RUN_TEST, instruction="Verificar status do serviço Windows", **overrides):
    values = {
        "step_id": f"step-{kind.value.lower()}",
        "step_type": kind,
        "status": PlanStepStatus.READY,
        "title": "Diagnóstico seguro",
        "instruction": instruction,
        "sequence": 0,
        "incident_id": "incident-1",
        "confidence": 0.8,
        "risk_level": RiskLevel.READ_ONLY,
        "requires_human": False,
        "requires_confirmation": False,
        "recommended_test": instruction if kind == PlanStepType.RUN_TEST else None,
        "recommended_action": instruction if kind in {PlanStepType.REQUEST_CONFIRMATION, PlanStepType.RECOMMEND_ACTION} else None,
    }
    values.update(overrides)
    return PlanStep(**values)


def plan(steps=None, **overrides):
    values = {
        "plan_id": "plan-1",
        "status": DiagnosticPlanStatus.ACTIVE,
        "incident_id": "incident-1",
        "primary_hypothesis_id": "incident-1",
        "confidence": 0.8,
        "steps": (step(),) if steps is None else steps,
        "current_step_id": None,
        "risk_level": RiskLevel.READ_ONLY,
        "reasoning": ("diagnostic reasoning",),
        "metadata": {"source": "planner"},
    }
    values.update(overrides)
    return DiagnosticPlan(**values)


def build(steps=None, policy=None, **plan_overrides):
    return DiagnosticExecutionEngine(policy).build_execution_plan(plan(steps, **plan_overrides))


def test_default_constructor():
    assert isinstance(DiagnosticExecutionEngine().policy, DiagnosticExecutionPolicy)


def test_custom_policy():
    policy = DiagnosticExecutionPolicy(allow_unknown_target=True)
    assert DiagnosticExecutionEngine(policy).policy is policy


def test_missing_diagnostic_plan_returns_failure():
    result = DiagnosticExecutionEngine().build_execution_plan(None)
    assert result.success is False and result.execution_plan is None and result.errors


def test_empty_plan_returns_blocked_result():
    result = build(steps=())
    assert result.success is False and result.execution_plan.actions == ()


def test_ask_question_generates_no_action():
    result = build([step(PlanStepType.ASK_QUESTION, "Qual terminal?")])
    assert result.execution_plan.actions == ()


def test_safe_run_test():
    result = build()
    assert result.success and result.selected_action.action_name == "check_service_status"
    assert result.selected_action.status == ExecutionStatus.READY


def test_verify_result():
    result = build([step(PlanStepType.VERIFY_RESULT, "Verificar resultado")], DiagnosticExecutionPolicy(allow_unknown_target=True))
    assert result.selected_action.action_name == "verify_result"


def test_request_confirmation_is_blocked():
    result = build([step(PlanStepType.REQUEST_CONFIRMATION, "Confirmar reinício do serviço")])
    assert result.selected_action.action_name == "request_confirmation"
    assert result.selected_action.status == ExecutionStatus.BLOCKED


def test_recommend_action_is_descriptive():
    policy = DiagnosticExecutionPolicy(allow_state_changing_actions=True)
    result = build([step(PlanStepType.RECOMMEND_ACTION, "Reiniciar serviço Windows")], policy)
    assert "no operation was executed" in result.selected_action.description


def test_escalation_stops_follow_up_actions():
    steps = [step(PlanStepType.ESCALATE_TO_HUMAN, "Escalar ao humano", sequence=0), step(sequence=1)]
    result = build(steps, DiagnosticExecutionPolicy(allow_unknown_target=True))
    assert len(result.execution_plan.actions) == 1
    assert result.selected_action.action_name == "escalate_to_human"


def test_complete_generates_no_action_and_succeeds():
    result = build([step(PlanStepType.COMPLETE, "Concluir")], status=DiagnosticPlanStatus.COMPLETED)
    assert result.success and result.execution_plan.status == ExecutionStatus.SUCCESS


@pytest.mark.parametrize(
    ("instruction", "target"),
    [
        ("Verificar serviço Windows", ExecutionTarget.WINDOWS),
        ("Executar ping no host", ExecutionTarget.NETWORK),
        ("Verificar status Linux", ExecutionTarget.LINUX),
        ("Verificar pelo Remote Agent", ExecutionTarget.REMOTE_AGENT),
        ("Validar configuração", ExecutionTarget.UNKNOWN),
    ],
)
def test_target_mapping(instruction, target):
    policy = DiagnosticExecutionPolicy(allow_linux=True, allow_remote_agent=True, allow_unknown_target=True)
    assert build([step(instruction=instruction)], policy).selected_action.target == target


@pytest.mark.parametrize(
    ("instruction", "risk"),
    [
        ("Verificar status do serviço", ExecutionRisk.LOW),
        ("Reiniciar serviço", ExecutionRisk.MEDIUM),
        ("Alterar firewall", ExecutionRisk.HIGH),
        ("Formatar servidor", ExecutionRisk.CRITICAL),
    ],
)
def test_risk_mapping(instruction, risk):
    policy = DiagnosticExecutionPolicy(
        allow_unknown_target=True, allow_high_risk=True, allow_critical_risk=True,
        allow_state_changing_actions=True, allow_destructive_actions=True,
    )
    assert build([step(PlanStepType.RECOMMEND_ACTION, instruction)], policy).selected_action.risk == risk


def test_blocked_target_is_not_changed():
    result = build([step(instruction="Validar configuração")])
    assert result.selected_action.target == ExecutionTarget.UNKNOWN
    assert result.selected_action.status == ExecutionStatus.BLOCKED


@pytest.mark.parametrize("risk", [RiskLevel.HIGH, RiskLevel.CRITICAL])
def test_blocked_risk_requires_human(risk):
    result = build([step(risk_level=risk)])
    assert result.selected_action.status == ExecutionStatus.BLOCKED
    assert result.selected_action.requires_human is True


def test_medium_risk_requires_confirmation():
    policy = DiagnosticExecutionPolicy(allow_state_changing_actions=True)
    result = build([step(instruction="Reiniciar serviço")], policy)
    assert result.selected_action.requires_confirmation is True
    assert result.selected_action.status == ExecutionStatus.BLOCKED


@pytest.mark.parametrize(
    ("instruction", "kind"),
    [
        ("Verificar status", "read_only"),
        ("Reiniciar serviço", "state_changing"),
        ("Apagar dados", "destructive"),
    ],
)
def test_action_kind_classification(instruction, kind):
    policy = DiagnosticExecutionPolicy(
        allow_unknown_target=True, allow_state_changing_actions=True, allow_destructive_actions=True,
        allow_critical_risk=True,
    )
    result = build([step(PlanStepType.RECOMMEND_ACTION, instruction)], policy)
    assert result.selected_action.metadata["action_kind"] == kind


def test_blocked_action_kind():
    result = build([step(instruction="Reiniciar serviço")])
    assert result.selected_action.status == ExecutionStatus.BLOCKED


def test_explicit_parameters_only():
    metadata = {"host": "server-1", "port": 443, "unrelated": "ignored"}
    result = build([step(instruction="Ping host", metadata=metadata)])
    assert [(item.key, item.value) for item in result.selected_action.parameters] == [("host", "server-1"), ("port", 443)]


def test_condition_can_supply_explicit_parameter():
    condition = PlanCondition("service_name", "equals", "Spooler", "Serviço explícito")
    result = build([step(preconditions=(condition,))])
    assert result.selected_action.parameters[0].value == "Spooler"


def test_parameters_are_not_invented():
    assert build().selected_action.parameters == ()


def test_parameter_limit():
    policy = DiagnosticExecutionPolicy(max_parameters_per_action=1)
    result = build([step(metadata={"host": "server", "port": 443})], policy)
    assert len(result.selected_action.parameters) == 1


def test_secret_parameter_is_removed():
    result = build([step(metadata={"host": "server", "password": "secret"})])
    assert [item.key for item in result.selected_action.parameters] == ["host"]
    assert "password" not in result.selected_action.metadata


def test_default_timeout():
    assert build().selected_action.timeout_seconds == 30


def test_custom_timeout_respects_configured_maximum():
    policy = DiagnosticExecutionPolicy(default_timeout_seconds=5, max_timeout_seconds=5)
    assert build(policy=policy).selected_action.timeout_seconds == 5


def test_deterministic_ids():
    result = build()
    assert result.selected_action.action_id == "action-001-check-service-status"


def test_stable_order_follows_step_sequence():
    steps = [step(instruction="Ping host", sequence=2, step_id="later"), step(sequence=1, step_id="first")]
    result = build(steps)
    assert [item.action_id for item in result.execution_plan.actions] == [
        "action-001-check-service-status", "action-002-ping-host"
    ]


def test_same_input_same_result():
    assert build() == build()


def test_max_actions_limit():
    steps = [step(sequence=index, step_id=f"step-{index}") for index in range(3)]
    result = build(steps, DiagnosticExecutionPolicy(max_actions=2))
    assert len(result.execution_plan.actions) == 2


def test_risk_limit_blocks_excess_action():
    steps = [step(sequence=index, step_id=f"step-{index}") for index in range(2)]
    policy = DiagnosticExecutionPolicy(max_low_risk_actions=1, stop_after_blocked=False)
    result = build(steps, policy)
    assert result.execution_plan.actions[1].status == ExecutionStatus.BLOCKED


def previous(status=ExecutionStatus.SUCCESS):
    generated = build().execution_plan
    old_action = replace(generated.actions[0], status=status)
    kwargs = {
        "completed_actions": (old_action.action_id,) if status == ExecutionStatus.SUCCESS else (),
        "failed_actions": (old_action.action_id,) if status == ExecutionStatus.FAILED else (),
        "cancelled_actions": (old_action.action_id,) if status == ExecutionStatus.CANCELLED else (),
    }
    return replace(generated, actions=(old_action,), current_action_id=None, **kwargs)


@pytest.mark.parametrize("status", [ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED])
def test_previous_terminal_status_is_preserved(status):
    old = previous(status)
    result = DiagnosticExecutionEngine().build_execution_plan(plan(), old)
    assert result.execution_plan.actions[0].status == status
    assert result.execution_plan.actions[0].action_id == old.actions[0].action_id


def test_previous_plan_id_is_preserved_when_coherent():
    old = previous()
    assert DiagnosticExecutionEngine().build_execution_plan(plan(), old).execution_plan.plan_id == old.plan_id


def test_equivalent_previous_action_is_not_duplicated():
    result = DiagnosticExecutionEngine().build_execution_plan(plan(), previous())
    assert len(result.execution_plan.actions) == 1


def test_previous_plan_is_not_mutated():
    old = previous()
    snapshot = deepcopy(old)
    DiagnosticExecutionEngine().build_execution_plan(plan(), old)
    assert old == snapshot


def test_diagnostic_plan_is_not_mutated():
    source = plan()
    snapshot = deepcopy(source)
    DiagnosticExecutionEngine().build_execution_plan(source)
    assert source == snapshot


def test_metadata_is_preserved_and_sanitized():
    result = build(metadata={"source": "planner", "password": "secret"})
    assert result.metadata["source"] == "planner"
    assert "password" not in result.metadata


def test_metadata_can_be_removed():
    result = build(policy=DiagnosticExecutionPolicy(preserve_metadata=False))
    assert result.metadata == {"source_diagnostic_plan_id": "plan-1"}


def test_reasoning_can_be_removed():
    result = build([step(PlanStepType.ASK_QUESTION, "Perguntar")], DiagnosticExecutionPolicy(preserve_reasoning=False))
    assert result.reasoning == ()


def test_reasoning_limit():
    steps = [step(PlanStepType.ASK_QUESTION, "Perguntar", sequence=index, step_id=f"q-{index}") for index in range(3)]
    result = build(steps, DiagnosticExecutionPolicy(max_reasoning_messages=1))
    assert len(result.reasoning) == 1


def test_error_limit():
    steps = [step(instruction="conteúdo sem mapeamento", sequence=index, step_id=f"x-{index}") for index in range(3)]
    policy = DiagnosticExecutionPolicy(max_errors=1, stop_after_blocked=False)
    assert len(build(steps, policy).errors) == 1


def test_stop_after_failed_previous_action():
    steps = [step(sequence=0), step(sequence=1, step_id="next")]
    result = DiagnosticExecutionEngine().build_execution_plan(plan(steps), previous(ExecutionStatus.FAILED))
    assert len(result.execution_plan.actions) == 1


def test_stop_after_blocked_action():
    steps = [step(instruction="Validar configuração", sequence=0), step(sequence=1, step_id="next")]
    assert len(build(steps).execution_plan.actions) == 1


@pytest.mark.parametrize(
    ("instruction", "risk"),
    [
        ("Apagar banco de dados", ExecutionRisk.CRITICAL),
        ("Alterar firewall", ExecutionRisk.HIGH),
        ("Alterar certificado digital", ExecutionRisk.HIGH),
        ("Atualizar BIOS", ExecutionRisk.CRITICAL),
    ],
)
def test_sensitive_content_is_blocked(instruction, risk):
    result = build([step(PlanStepType.RECOMMEND_ACTION, instruction)])
    assert result.selected_action.risk == risk
    assert result.selected_action.status == ExecutionStatus.BLOCKED


@pytest.mark.parametrize("instruction", ["Verificar status", "Consultar serviço", "Listar processos", "Ping host"])
def test_safe_read_only_content(instruction):
    policy = DiagnosticExecutionPolicy(allow_unknown_target=True)
    result = build([step(instruction=instruction)], policy)
    assert result.selected_action.metadata["action_kind"] == "read_only"


def test_no_action_starts_running():
    assert all(item.status != ExecutionStatus.RUNNING for item in build().execution_plan.actions)


def test_public_import():
    from app.services.diagnostic_engine import DiagnosticExecutionEngine as PublicEngine

    assert PublicEngine is DiagnosticExecutionEngine


def test_files_are_utf8_without_bom():
    root = Path(__file__).parents[3]
    for path in (
        root / "app/services/diagnostic_engine/execution_engine.py",
        root / "app/services/diagnostic_engine/__init__.py",
        Path(__file__),
    ):
        content = path.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
