from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    DiagnosticPlan,
    DiagnosticPlanResult,
    DiagnosticPlanStatus,
    PlanCondition,
    PlanStep,
    PlanStepStatus,
    PlanStepType,
)
from app.services.diagnostic_engine.decision_models import DecisionType
from app.services.diagnostic_engine.enums import RiskLevel


def condition(**overrides):
    values = {
        "key": "terminal",
        "operator": "equals",
        "expected_value": "caixa 1",
        "description": "Terminal deve corresponder",
    }
    values.update(overrides)
    return PlanCondition(**values)


def step(step_id="step-1", sequence=0, **overrides):
    values = {
        "step_id": step_id,
        "step_type": PlanStepType.ASK_QUESTION,
        "status": PlanStepStatus.PENDING,
        "title": "Identificar terminal",
        "instruction": "Perguntar qual terminal foi afetado.",
        "sequence": sequence,
        "incident_id": "incident-1",
        "confidence": 0.75,
        "risk_level": RiskLevel.READ_ONLY,
        "requires_human": False,
        "requires_confirmation": False,
        "question": "Qual terminal foi afetado?",
    }
    values.update(overrides)
    return PlanStep(**values)


def plan(steps=None, **overrides):
    values = {
        "plan_id": "plan-1",
        "status": DiagnosticPlanStatus.ACTIVE,
        "incident_id": "incident-1",
        "primary_hypothesis_id": "hypothesis-1",
        "confidence": 0.8,
        "steps": (step(),) if steps is None else steps,
        "current_step_id": "step-1",
        "created_from_decision_type": DecisionType.ASK_QUESTION,
        "risk_level": RiskLevel.READ_ONLY,
        "reasoning": ("Informação necessária",),
    }
    values.update(overrides)
    return DiagnosticPlan(**values)


@pytest.mark.parametrize("enum_type", [PlanStepType, PlanStepStatus, DiagnosticPlanStatus])
def test_enums_are_string_enums(enum_type):
    assert all(item.value == item.name and isinstance(item, str) for item in enum_type)


@pytest.mark.parametrize("member", list(PlanStepType))
def test_plan_step_type_members_are_stable(member):
    assert PlanStepType(member.value) is member


@pytest.mark.parametrize("member", list(PlanStepStatus))
def test_plan_step_status_members_are_stable(member):
    assert PlanStepStatus(member.value) is member


@pytest.mark.parametrize("member", list(DiagnosticPlanStatus))
def test_diagnostic_plan_status_members_are_stable(member):
    assert DiagnosticPlanStatus(member.value) is member


def test_plan_condition_creation():
    item = condition()
    assert (item.key, item.operator, item.expected_value, item.required) == ("terminal", "equals", "caixa 1", True)


@pytest.mark.parametrize(("field", "value"), [("key", ""), ("key", "  "), ("operator", ""), ("description", "")])
def test_plan_condition_rejects_empty_text(field, value):
    with pytest.raises(ValueError, match=field):
        condition(**{field: value})


def test_plan_condition_defensive_copies():
    expected = {"items": [1]}
    metadata = {"source": {"name": "test"}}
    item = condition(expected_value=expected, metadata=metadata)
    expected["items"].append(2)
    metadata["source"]["name"] = "changed"
    assert item.expected_value == {"items": [1]}
    assert item.metadata == {"source": {"name": "test"}}


def test_plan_condition_is_immutable():
    with pytest.raises(FrozenInstanceError):
        condition().key = "changed"


def test_plan_condition_equality():
    assert condition() == condition()


def test_plan_step_creation():
    item = step()
    assert item.step_id == "step-1"
    assert item.step_type == PlanStepType.ASK_QUESTION
    assert item.status == PlanStepStatus.PENDING


@pytest.mark.parametrize(("field", "value"), [("step_id", ""), ("title", " "), ("instruction", "")])
def test_plan_step_rejects_empty_required_text(field, value):
    with pytest.raises(ValueError, match=field):
        step(**{field: value})


@pytest.mark.parametrize("sequence", [-1, -10, 1.5, True])
def test_plan_step_rejects_invalid_sequence(sequence):
    with pytest.raises(ValueError, match="sequence"):
        step(sequence=sequence)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, "0.5", True])
def test_plan_step_rejects_invalid_confidence(confidence):
    with pytest.raises(ValueError, match="confidence"):
        step(confidence=confidence)


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_plan_step_accepts_confidence_boundaries(confidence):
    assert step(confidence=confidence).confidence == confidence


def test_plan_step_rejects_empty_dependency():
    with pytest.raises(ValueError, match="depends_on"):
        step(depends_on=("",))


def test_plan_step_rejects_self_dependency():
    with pytest.raises(ValueError, match="itself"):
        step(depends_on=("step-1",))


def test_plan_step_rejects_duplicate_dependency():
    with pytest.raises(ValueError, match="unique"):
        step(depends_on=("step-0", "step-0"))


def test_plan_step_converts_collections_to_tuples():
    item = step(
        preconditions=[condition()],
        success_conditions=[condition(key="success")],
        failure_conditions=[condition(key="failure")],
        depends_on=["step-0"],
        evidence_required=["terminal"],
    )
    assert all(isinstance(getattr(item, name), tuple) for name in (
        "preconditions", "success_conditions", "failure_conditions", "depends_on", "evidence_required"
    ))


def test_plan_step_defensive_copies():
    dependencies = ["step-0"]
    metadata = {"nested": [1]}
    item = step(depends_on=dependencies, metadata=metadata)
    dependencies.append("step-x")
    metadata["nested"].append(2)
    assert item.depends_on == ("step-0",)
    assert item.metadata == {"nested": [1]}


def test_plan_step_is_immutable():
    with pytest.raises(FrozenInstanceError):
        step().status = PlanStepStatus.COMPLETED


def test_plan_step_equality():
    assert step() == step()


def test_diagnostic_plan_creation():
    item = plan()
    assert item.plan_id == "plan-1"
    assert item.steps == (step(),)


@pytest.mark.parametrize("plan_id", ["", "   "])
def test_diagnostic_plan_rejects_empty_id(plan_id):
    with pytest.raises(ValueError, match="plan_id"):
        plan(plan_id=plan_id)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, "0.8", True])
def test_diagnostic_plan_rejects_invalid_confidence(confidence):
    with pytest.raises(ValueError, match="confidence"):
        plan(confidence=confidence)


def test_diagnostic_plan_rejects_duplicate_step_ids():
    with pytest.raises(ValueError, match="step_id"):
        plan(steps=(step(sequence=0), step(sequence=1)))


def test_diagnostic_plan_rejects_unknown_current_step():
    with pytest.raises(ValueError, match="current_step_id"):
        plan(current_step_id="missing")


@pytest.mark.parametrize("field", ["completed_step_ids", "skipped_step_ids", "failed_step_ids"])
def test_diagnostic_plan_rejects_unknown_state_id(field):
    with pytest.raises(ValueError, match=field):
        plan(**{field: ("missing",)})


@pytest.mark.parametrize("field", ["completed_step_ids", "skipped_step_ids", "failed_step_ids"])
def test_diagnostic_plan_rejects_duplicate_state_id(field):
    with pytest.raises(ValueError, match=field):
        plan(**{field: ("step-1", "step-1")})


@pytest.mark.parametrize(
    "states",
    [
        {"completed_step_ids": ("step-1",), "skipped_step_ids": ("step-1",)},
        {"completed_step_ids": ("step-1",), "failed_step_ids": ("step-1",)},
        {"skipped_step_ids": ("step-1",), "failed_step_ids": ("step-1",)},
    ],
)
def test_diagnostic_plan_rejects_conflicting_states(states):
    with pytest.raises(ValueError, match="conflicting"):
        plan(**states)


def test_diagnostic_plan_sorts_steps_deterministically():
    later = step("b", 2)
    same_sequence_b = step("b-first", 1)
    same_sequence_a = step("a-first", 1)
    item = plan(steps=[later, same_sequence_b, same_sequence_a], current_step_id="a-first")
    assert [current.step_id for current in item.steps] == ["a-first", "b-first", "b"]


def test_diagnostic_plan_converts_collections_to_tuples():
    item = plan(completed_step_ids=["step-1"], current_step_id=None, reasoning=["reason"], errors=["error"])
    assert item.completed_step_ids == ("step-1",)
    assert item.reasoning == ("reason",)
    assert item.errors == ("error",)


def test_diagnostic_plan_defensive_copies():
    steps = [step()]
    metadata = {"nested": [1]}
    item = plan(steps=steps, metadata=metadata)
    steps.clear()
    metadata["nested"].append(2)
    assert len(item.steps) == 1
    assert item.metadata == {"nested": [1]}


def test_diagnostic_plan_is_immutable():
    with pytest.raises(FrozenInstanceError):
        plan().status = DiagnosticPlanStatus.COMPLETED


def test_diagnostic_plan_equality():
    assert plan() == plan()


def test_diagnostic_plan_result_creation():
    diagnostic_plan = plan()
    result = DiagnosticPlanResult(diagnostic_plan, True, diagnostic_plan.steps[0])
    assert result.success is True
    assert result.selected_step == step()


def test_diagnostic_plan_result_rejects_success_without_plan():
    with pytest.raises(ValueError, match="requires a plan"):
        DiagnosticPlanResult(success=True)


def test_diagnostic_plan_result_rejects_selected_step_outside_plan():
    with pytest.raises(ValueError, match="selected_step"):
        DiagnosticPlanResult(plan(), False, step("outside", 2))


def test_diagnostic_plan_result_rejects_divergent_step_with_known_id():
    with pytest.raises(ValueError, match="selected_step"):
        DiagnosticPlanResult(plan(), selected_step=step(title="Different title"))


def test_diagnostic_plan_result_rejects_duplicate_alternative():
    alternative = step("alternative", 2)
    with pytest.raises(ValueError, match="duplicates"):
        DiagnosticPlanResult(plan(), alternatives=(alternative, alternative))


def test_diagnostic_plan_result_rejects_selected_step_as_alternative():
    diagnostic_plan = plan()
    selected = diagnostic_plan.steps[0]
    with pytest.raises(ValueError, match="alternatives"):
        DiagnosticPlanResult(diagnostic_plan, selected_step=selected, alternatives=(selected,))


def test_diagnostic_plan_result_converts_collections_and_copies_metadata():
    metadata = {"nested": [1]}
    result = DiagnosticPlanResult(plan(), alternatives=[step("alternative", 2)], reasoning=["r"], errors=["e"], metadata=metadata)
    metadata["nested"].append(2)
    assert isinstance(result.alternatives, tuple)
    assert result.reasoning == ("r",)
    assert result.errors == ("e",)
    assert result.metadata == {"nested": [1]}


def test_diagnostic_plan_result_is_immutable():
    with pytest.raises(FrozenInstanceError):
        DiagnosticPlanResult().success = True


@pytest.mark.parametrize("model", [condition(), step(), plan(), DiagnosticPlanResult(plan=plan())])
def test_models_serialize_with_asdict(model):
    assert isinstance(asdict(model), dict)


def test_public_imports_are_available():
    import app.services.diagnostic_engine as public

    for name in (
        "PlanStepType", "PlanStepStatus", "DiagnosticPlanStatus", "PlanCondition", "PlanStep",
        "DiagnosticPlan", "DiagnosticPlanResult",
    ):
        assert getattr(public, name) is globals()[name]


def test_repr_is_deterministic():
    assert repr(plan()) == repr(plan())
    assert "0x" not in repr(plan())


def test_inputs_are_not_mutated():
    source_steps = [step()]
    source_reasoning = ["reason"]
    plan(steps=source_steps, reasoning=source_reasoning)
    assert source_steps == [step()]
    assert source_reasoning == ["reason"]


def test_files_are_utf8_without_bom():
    root = Path(__file__).parents[3]
    paths = (
        root / "app/services/diagnostic_engine/planner_models.py",
        root / "app/services/diagnostic_engine/__init__.py",
        Path(__file__),
    )
    for path in paths:
        content = path.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
