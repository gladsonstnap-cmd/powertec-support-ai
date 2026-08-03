from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.diagnostic_engine import DiagnosticPlannerEngine
from app.services.diagnostic_engine.decision_models import Decision, DecisionPriority, DecisionType
from app.services.diagnostic_engine.enums import RiskLevel
from app.services.diagnostic_engine.knowledge_models import DiagnosticQuestion, DiagnosticTest
from app.services.diagnostic_engine.memory_models import MemorySnapshot
from app.services.diagnostic_engine.planner_models import (
    DiagnosticPlan,
    DiagnosticPlanStatus,
    PlanStep,
    PlanStepStatus,
    PlanStepType,
)
from app.services.diagnostic_engine.planner_policy import DiagnosticPlannerPolicy


def make_decision(kind=DecisionType.ASK_QUESTION, **overrides):
    values = {
        "decision_type": kind,
        "priority": DecisionPriority.NORMAL,
        "title": "Decisão",
        "message": "Orientação segura.",
        "reasoning": ("regra",),
        "confidence": 0.75,
        "incident_id": "incident-1",
        "requires_human": False,
        "risk_level": RiskLevel.LOW,
        "next_question": "Qual terminal foi afetado?" if kind == DecisionType.ASK_QUESTION else None,
        "recommended_test": "Ping" if kind == DecisionType.RUN_TEST else None,
        "recommended_action": "Reiniciar serviço" if kind in {DecisionType.REQUEST_CONFIRMATION, DecisionType.RECOMMEND_ACTION} else None,
        "confirmation_required": kind == DecisionType.REQUEST_CONFIRMATION,
        "completion_reason": "Solução confirmada" if kind == DecisionType.COMPLETE else None,
        "metadata": {"source": "decision"},
    }
    values.update(overrides)
    return Decision(**values)


def make_hypothesis(incident_id="incident-1", confidence=0.8, **overrides):
    values = {
        "incident_id": incident_id,
        "confidence": confidence,
        "requires_human": False,
        "risk_level": RiskLevel.LOW,
        "next_questions": [DiagnosticQuestion("q1", "Qual terminal?", "terminal", 1, "text")],
        "recommended_tests": [],
        "recommended_actions": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def build(kind=DecisionType.ASK_QUESTION, *, hypotheses=None, policy=None, **decision_overrides):
    engine = DiagnosticPlannerEngine(policy)
    return engine.build_plan(hypotheses or [make_hypothesis()], make_decision(kind, **decision_overrides))


def old_step(status=PlanStepStatus.COMPLETED, **overrides):
    values = {
        "step_id": "step-001-ask-question",
        "step_type": PlanStepType.ASK_QUESTION,
        "status": status,
        "title": "Pergunta anterior",
        "instruction": "Qual terminal foi afetado?",
        "sequence": 0,
        "incident_id": "incident-1",
        "confidence": 0.75,
        "risk_level": RiskLevel.LOW,
        "requires_human": False,
        "requires_confirmation": False,
        "question": "Qual terminal foi afetado?",
    }
    values.update(overrides)
    return PlanStep(**values)


def old_plan(steps=None, **overrides):
    values = {
        "plan_id": "plan-existing",
        "status": DiagnosticPlanStatus.ACTIVE,
        "incident_id": "incident-1",
        "primary_hypothesis_id": "incident-1",
        "confidence": 0.75,
        "steps": tuple(steps or [old_step()]),
        "completed_step_ids": ("step-001-ask-question",),
        "risk_level": RiskLevel.LOW,
        "metadata": {"origin": "previous"},
    }
    values.update(overrides)
    return DiagnosticPlan(**values)


def test_default_constructor():
    assert isinstance(DiagnosticPlannerEngine().policy, DiagnosticPlannerPolicy)


def test_custom_policy():
    policy = DiagnosticPlannerPolicy(max_steps=2)
    assert DiagnosticPlannerEngine(policy).policy is policy


def test_ask_question_plan():
    result = build()
    assert result.success and result.selected_step.step_type == PlanStepType.ASK_QUESTION
    assert result.plan.status == DiagnosticPlanStatus.WAITING_USER


def test_run_test_plan():
    result = build(DecisionType.RUN_TEST)
    assert result.selected_step.recommended_test == "Ping"
    assert result.plan.status == DiagnosticPlanStatus.ACTIVE


def test_verify_result_depends_on_test():
    diagnostic_test = DiagnosticTest("ping", "Ping", "Consultar rede", "ping", RiskLevel.READ_ONLY, False, False, ["resposta"])
    result = build(DecisionType.RUN_TEST, hypotheses=[make_hypothesis(recommended_tests=[diagnostic_test])])
    verify = result.plan.steps[1]
    assert verify.step_type == PlanStepType.VERIFY_RESULT
    assert verify.depends_on == (result.plan.steps[0].step_id,)
    assert verify.success_conditions[0].expected_value == "resposta"


def test_request_confirmation_plan():
    result = build(DecisionType.REQUEST_CONFIRMATION)
    assert result.selected_step.step_type == PlanStepType.REQUEST_CONFIRMATION
    assert result.plan.status == DiagnosticPlanStatus.WAITING_CONFIRMATION


def test_recommend_action_plan():
    result = build(DecisionType.RECOMMEND_ACTION)
    assert result.selected_step.step_type == PlanStepType.RECOMMEND_ACTION
    assert "sem executá-la" in result.selected_step.instruction


def test_medium_risk_confirmation_when_required():
    policy = DiagnosticPlannerPolicy(require_confirmation_for_medium_risk=True)
    result = build(DecisionType.RECOMMEND_ACTION, policy=policy, risk_level=RiskLevel.MEDIUM)
    assert [item.step_type for item in result.plan.steps] == [PlanStepType.REQUEST_CONFIRMATION, PlanStepType.RECOMMEND_ACTION]
    assert result.plan.steps[1].depends_on == (result.plan.steps[0].step_id,)


def test_escalation_decision():
    result = build(DecisionType.ESCALATE_TO_HUMAN)
    assert result.plan.status == DiagnosticPlanStatus.ESCALATED
    assert result.selected_step.requires_human


def test_complete_decision():
    result = build(DecisionType.COMPLETE)
    assert result.plan.status == DiagnosticPlanStatus.COMPLETED
    assert len(result.plan.steps) == 1


def test_insufficient_information_uses_existing_question():
    result = build(DecisionType.INSUFFICIENT_INFORMATION)
    assert result.selected_step.question == "Qual terminal?"


def test_insufficient_information_without_question_escalates():
    result = build(DecisionType.INSUFFICIENT_INFORMATION, hypotheses=[make_hypothesis(next_questions=[])])
    assert result.plan.status == DiagnosticPlanStatus.ESCALATED


def test_without_decision_returns_failure():
    result = DiagnosticPlannerEngine().build_plan([make_hypothesis()])
    assert not result.success and result.plan is None and result.errors


def test_without_hypothesis_uses_decision_incident():
    result = DiagnosticPlannerEngine().build_plan([], make_decision())
    assert result.plan.incident_id == "incident-1"
    assert result.plan.primary_hypothesis_id is None


def test_dominant_hypothesis_is_highest_confidence():
    result = build(hypotheses=[make_hypothesis("low", 0.5), make_hypothesis("high", 0.9)])
    assert result.plan.primary_hypothesis_id == "high"


def test_dominant_hypothesis_tie_breaks_by_incident_id():
    result = build(hypotheses=[make_hypothesis("b", 0.8), make_hypothesis("a", 0.8)])
    assert result.plan.primary_hypothesis_id == "a"


def test_alternatives_are_created_and_ordered():
    hypotheses = [make_hypothesis("main", 0.9), make_hypothesis("b", 0.6), make_hypothesis("a", 0.7)]
    result = build(hypotheses=hypotheses)
    assert [item.incident_id for item in result.alternatives] == ["a", "b"]


def test_alternative_limit():
    policy = DiagnosticPlannerPolicy(max_parallel_alternatives=1)
    result = build(hypotheses=[make_hypothesis("main", .9), make_hypothesis("a", .8), make_hypothesis("b", .7)], policy=policy)
    assert len(result.alternatives) == 1


def test_alternatives_can_be_disabled():
    policy = DiagnosticPlannerPolicy(allow_parallel_alternatives=False)
    assert build(hypotheses=[make_hypothesis("main", .9), make_hypothesis("a", .8)], policy=policy).alternatives == ()


def test_steps_have_stable_order():
    result = build(DecisionType.RUN_TEST)
    assert list(result.plan.steps) == sorted(result.plan.steps, key=lambda item: (item.sequence, item.step_id))


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (DecisionType.ASK_QUESTION, "step-001-ask-question"),
        (DecisionType.RUN_TEST, "step-001-run-test"),
        (DecisionType.REQUEST_CONFIRMATION, "step-001-request-confirmation"),
        (DecisionType.RECOMMEND_ACTION, "step-001-recommend-action"),
        (DecisionType.ESCALATE_TO_HUMAN, "step-001-escalate-to-human"),
        (DecisionType.COMPLETE, "step-001-complete"),
    ],
)
def test_deterministic_step_ids(kind, expected):
    assert build(kind).plan.steps[0].step_id == expected


def test_same_input_generates_same_plan():
    assert build().plan == build().plan


def test_max_steps_with_previous_plan():
    policy = DiagnosticPlannerPolicy(max_steps=1)
    previous = old_plan()
    result = DiagnosticPlannerEngine(policy).build_plan([make_hypothesis()], make_decision(DecisionType.RUN_TEST), previous_plan=previous)
    assert len(result.plan.steps) == 1


@pytest.mark.parametrize(
    ("field", "step_type", "decision"),
    [
        ("max_question_steps", PlanStepType.ASK_QUESTION, make_decision()),
        ("max_test_steps", PlanStepType.RUN_TEST, make_decision(DecisionType.RUN_TEST)),
        ("max_confirmation_steps", PlanStepType.REQUEST_CONFIRMATION, make_decision(DecisionType.REQUEST_CONFIRMATION)),
        ("max_action_steps", PlanStepType.RECOMMEND_ACTION, make_decision(DecisionType.RECOMMEND_ACTION)),
    ],
)
def test_type_limits_are_respected(field, step_type, decision):
    existing = old_step(step_type=step_type, question=decision.next_question, recommended_test=decision.recommended_test, recommended_action=decision.recommended_action)
    previous = old_plan([existing])
    policy = DiagnosticPlannerPolicy(**{field: 1})
    result = DiagnosticPlannerEngine(policy).build_plan([make_hypothesis()], decision, previous_plan=previous)
    assert sum(item.step_type == step_type for item in result.plan.steps) <= 1


def test_minimum_step_confidence_blocks_test():
    policy = DiagnosticPlannerPolicy(minimum_step_confidence=.8, minimum_plan_confidence=.5)
    result = build(DecisionType.RUN_TEST, policy=policy, confidence=.7)
    assert not result.success and result.plan is None


def test_minimum_plan_confidence_returns_failure():
    policy = DiagnosticPlannerPolicy(minimum_plan_confidence=.8)
    result = build(policy=policy, confidence=.7)
    assert not result.success and result.plan is None


def test_stop_after_escalation():
    assert len(build(DecisionType.ESCALATE_TO_HUMAN).plan.steps) == 1


def test_escalation_can_include_completion_when_not_stopped():
    policy = DiagnosticPlannerPolicy(stop_after_escalation=False)
    assert [item.step_type for item in build(DecisionType.ESCALATE_TO_HUMAN, policy=policy).plan.steps] == [PlanStepType.ESCALATE_TO_HUMAN, PlanStepType.COMPLETE]


def test_stop_after_completion():
    assert len(build(DecisionType.COMPLETE).plan.steps) == 1


@pytest.mark.parametrize("action", ["Apagar banco de dados", "Formatar servidor", "Alterar certificado fiscal"])
def test_sensitive_or_destructive_action_escalates(action):
    result = build(DecisionType.RECOMMEND_ACTION, recommended_action=action)
    assert result.plan.status == DiagnosticPlanStatus.ESCALATED


@pytest.mark.parametrize("test_name", ["Ping", "Verificar status", "Consultar serviço"])
def test_safe_read_only_test_is_planned(test_name):
    result = build(DecisionType.RUN_TEST, recommended_test=test_name)
    assert result.selected_step.step_type == PlanStepType.RUN_TEST


@pytest.mark.parametrize("test_name", ["Atualizar firmware", "Abrir regedit", "Validar senha"])
def test_sensitive_test_escalates(test_name):
    assert build(DecisionType.RUN_TEST, recommended_test=test_name).plan.status == DiagnosticPlanStatus.ESCALATED


@pytest.mark.parametrize(
    ("risk", "status"),
    [
        (RiskLevel.LOW, DiagnosticPlanStatus.ACTIVE),
        (RiskLevel.MEDIUM, DiagnosticPlanStatus.ACTIVE),
        (RiskLevel.HIGH, DiagnosticPlanStatus.ESCALATED),
        (RiskLevel.CRITICAL, DiagnosticPlanStatus.ESCALATED),
    ],
)
def test_risk_mapping(risk, status):
    result = build(DecisionType.RECOMMEND_ACTION, risk_level=risk)
    assert result.plan.status == status


def test_previous_plan_id_is_reused():
    result = DiagnosticPlannerEngine().build_plan([make_hypothesis()], make_decision(DecisionType.RUN_TEST), previous_plan=old_plan())
    assert result.plan.plan_id == "plan-existing"


@pytest.mark.parametrize("status", [PlanStepStatus.COMPLETED, PlanStepStatus.SKIPPED, PlanStepStatus.FAILED])
def test_previous_terminal_steps_are_preserved(status):
    existing = old_step(status=status)
    kwargs = {
        "completed_step_ids": (),
        "skipped_step_ids": (),
        "failed_step_ids": (),
        f"{status.value.lower()}_step_ids": (existing.step_id,),
    }
    previous = old_plan([existing], **kwargs)
    result = DiagnosticPlannerEngine().build_plan([make_hypothesis()], make_decision(), previous_plan=previous)
    assert existing in result.plan.steps


def test_equivalent_previous_step_is_not_duplicated():
    result = DiagnosticPlannerEngine().build_plan([make_hypothesis()], make_decision(), previous_plan=old_plan())
    assert len(result.plan.steps) == 1


def test_previous_plan_is_not_mutated():
    previous = old_plan()
    snapshot = deepcopy(previous)
    DiagnosticPlannerEngine().build_plan([make_hypothesis()], make_decision(DecisionType.RUN_TEST), previous_plan=previous)
    assert previous == snapshot


def test_hypotheses_are_not_mutated():
    hypotheses = [make_hypothesis()]
    snapshot = deepcopy(hypotheses)
    DiagnosticPlannerEngine().build_plan(hypotheses, make_decision())
    assert hypotheses == snapshot


def test_decision_is_not_mutated():
    item = make_decision()
    snapshot = deepcopy(item)
    DiagnosticPlannerEngine().build_plan([make_hypothesis()], item)
    assert item == snapshot


def test_memory_is_not_mutated():
    memory = MemorySnapshot(known_information={"terminal": ["caixa 1"]})
    snapshot = deepcopy(memory)
    DiagnosticPlannerEngine().build_plan([make_hypothesis()], make_decision(), memory_snapshot=memory)
    assert memory == snapshot


def test_reasoning_limit_and_preservation_flag():
    result = build(policy=DiagnosticPlannerPolicy(max_reasoning_messages=1))
    assert len(result.reasoning) <= 1
    assert build(policy=DiagnosticPlannerPolicy(preserve_reasoning=False)).reasoning == ()


def test_error_limit():
    policy = DiagnosticPlannerPolicy(max_errors=1)
    result = DiagnosticPlannerEngine(policy).build_plan([], None)
    assert len(result.errors) <= 1


def test_metadata_is_preserved():
    assert build().metadata == {"source": "decision"}


def test_metadata_can_be_removed():
    assert build(policy=DiagnosticPlannerPolicy(preserve_metadata=False)).metadata == {}


def test_public_import():
    from app.services.diagnostic_engine import DiagnosticPlannerEngine as PublicEngine

    assert PublicEngine is DiagnosticPlannerEngine


def test_files_are_utf8_without_bom():
    root = Path(__file__).parents[3]
    for path in (
        root / "app/services/diagnostic_engine/planner_engine.py",
        root / "app/services/diagnostic_engine/__init__.py",
        Path(__file__),
    ):
        content = path.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
