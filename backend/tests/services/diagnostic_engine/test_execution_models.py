from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    ExecutionAction,
    ExecutionParameter,
    ExecutionPlan,
    ExecutionResult,
    ExecutionRisk,
    ExecutionStatus,
    ExecutionTarget,
)


def parameter(**overrides):
    values = {
        "key": "terminal",
        "value": "caixa-1",
        "required": True,
        "description": "Terminal afetado",
    }
    values.update(overrides)
    return ExecutionParameter(**values)


def action(action_id="action-1", **overrides):
    values = {
        "action_id": action_id,
        "action_name": "collect_diagnostic",
        "title": "Coletar diagnóstico",
        "description": "Descreve uma coleta futura sem executá-la.",
        "target": ExecutionTarget.LOCAL_MACHINE,
        "status": ExecutionStatus.PENDING,
        "risk": ExecutionRisk.LOW,
        "parameters": (parameter(),),
        "timeout_seconds": 30,
        "requires_confirmation": False,
        "requires_human": False,
    }
    values.update(overrides)
    return ExecutionAction(**values)


def plan(actions=None, **overrides):
    values = {
        "plan_id": "execution-plan-1",
        "status": ExecutionStatus.PENDING,
        "actions": (action(),) if actions is None else actions,
        "current_action_id": "action-1",
    }
    values.update(overrides)
    return ExecutionPlan(**values)


@pytest.mark.parametrize("enum_type", [ExecutionStatus, ExecutionTarget, ExecutionRisk])
def test_enums_are_string_enums(enum_type):
    assert all(member.value == member.name and isinstance(member, str) for member in enum_type)


@pytest.mark.parametrize("member", list(ExecutionStatus))
def test_execution_status_members_are_stable(member):
    assert ExecutionStatus(member.value) is member


@pytest.mark.parametrize("member", list(ExecutionTarget))
def test_execution_target_members_are_stable(member):
    assert ExecutionTarget(member.value) is member


@pytest.mark.parametrize("member", list(ExecutionRisk))
def test_execution_risk_members_are_stable(member):
    assert ExecutionRisk(member.value) is member


def test_parameter_creation():
    assert parameter().key == "terminal"


@pytest.mark.parametrize("key", ["", "   ", None])
def test_parameter_rejects_empty_key(key):
    with pytest.raises(ValueError, match="key"):
        parameter(key=key)


def test_parameter_is_immutable():
    with pytest.raises(FrozenInstanceError):
        parameter().key = "changed"


def test_parameter_equality_and_hash():
    assert parameter() == parameter()
    assert hash(parameter()) == hash(parameter())


def test_parameter_defensive_copies():
    value = {"items": [1]}
    metadata = {"nested": [1]}
    item = parameter(value=value, metadata=metadata)
    value["items"].append(2)
    metadata["nested"].append(2)
    assert item.value == {"items": [1]}
    assert item.metadata == {"nested": [1]}


def test_action_creation():
    item = action()
    assert item.action_id == "action-1"
    assert item.parameters == (parameter(),)


@pytest.mark.parametrize(("field", "value"), [("action_id", ""), ("action_id", "  "), ("action_name", ""), ("action_name", None)])
def test_action_rejects_empty_required_text(field, value):
    with pytest.raises(ValueError, match=field):
        action(**{field: value})


@pytest.mark.parametrize("timeout", [0, -1, -0.1, True, "30", None])
def test_action_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="timeout_seconds"):
        action(timeout_seconds=timeout)


@pytest.mark.parametrize("timeout", [0.1, 1, 3600])
def test_action_accepts_positive_timeout(timeout):
    assert action(timeout_seconds=timeout).timeout_seconds == timeout


def test_action_converts_parameters_to_tuple_and_copies_metadata():
    parameters = [parameter()]
    metadata = {"nested": [1]}
    item = action(parameters=parameters, metadata=metadata)
    parameters.clear()
    metadata["nested"].append(2)
    assert item.parameters == (parameter(),)
    assert item.metadata == {"nested": [1]}


def test_action_is_immutable():
    with pytest.raises(FrozenInstanceError):
        action().status = ExecutionStatus.SUCCESS


def test_action_equality_and_hash():
    assert action() == action()
    assert hash(action()) == hash(action())


def test_plan_creation_and_defaults():
    item = plan()
    assert item.actions == (action(),)
    assert item.errors == ()


@pytest.mark.parametrize("plan_id", ["", " ", None])
def test_plan_rejects_empty_id(plan_id):
    with pytest.raises(ValueError, match="plan_id"):
        plan(plan_id=plan_id)


def test_plan_rejects_duplicate_action_ids():
    with pytest.raises(ValueError, match="action_id"):
        plan(actions=(action(), action()))


def test_plan_rejects_unknown_current_action():
    with pytest.raises(ValueError, match="current_action_id"):
        plan(current_action_id="missing")


@pytest.mark.parametrize("field", ["completed_actions", "failed_actions", "cancelled_actions"])
def test_plan_rejects_unknown_terminal_action(field):
    with pytest.raises(ValueError, match=field):
        plan(**{field: ("missing",)})


@pytest.mark.parametrize("field", ["completed_actions", "failed_actions", "cancelled_actions"])
def test_plan_rejects_duplicate_terminal_action(field):
    with pytest.raises(ValueError, match=field):
        plan(**{field: ("action-1", "action-1")})


@pytest.mark.parametrize("states", [
    {"completed_actions": ("action-1",), "failed_actions": ("action-1",)},
    {"completed_actions": ("action-1",), "cancelled_actions": ("action-1",)},
    {"failed_actions": ("action-1",), "cancelled_actions": ("action-1",)},
])
def test_plan_rejects_conflicting_terminal_states(states):
    with pytest.raises(ValueError, match="conflicting"):
        plan(**states)


def test_plan_sorts_actions_by_id():
    item = plan(actions=[action("z"), action("a")], current_action_id="a")
    assert tuple(entry.action_id for entry in item.actions) == ("a", "z")


def test_plan_converts_collections_to_tuples():
    item = plan(completed_actions=["action-1"], current_action_id=None, errors=["error"])
    assert item.completed_actions == ("action-1",)
    assert item.errors == ("error",)


def test_plan_defensive_copies():
    actions = [action()]
    metadata = {"nested": [1]}
    errors = ["error"]
    item = plan(actions=actions, metadata=metadata, errors=errors)
    actions.clear()
    metadata["nested"].append(2)
    errors.append("other")
    assert len(item.actions) == 1
    assert item.metadata == {"nested": [1]}
    assert item.errors == ("error",)


def test_plan_is_immutable():
    with pytest.raises(FrozenInstanceError):
        plan().status = ExecutionStatus.SUCCESS


def test_plan_equality_and_hash():
    assert plan() == plan()
    assert hash(plan()) == hash(plan())


def test_result_creation():
    execution_plan = plan()
    result = ExecutionResult(True, execution_plan, execution_plan.actions[0])
    assert result.success is True
    assert result.selected_action == action()


def test_result_rejects_success_without_plan():
    with pytest.raises(ValueError, match="requires an execution_plan"):
        ExecutionResult(success=True)


def test_result_rejects_selected_action_without_plan():
    with pytest.raises(ValueError, match="selected_action"):
        ExecutionResult(selected_action=action())


def test_result_rejects_selected_action_outside_plan():
    with pytest.raises(ValueError, match="selected_action"):
        ExecutionResult(execution_plan=plan(), selected_action=action("outside"))


def test_result_rejects_divergent_action_with_known_id():
    with pytest.raises(ValueError, match="selected_action"):
        ExecutionResult(execution_plan=plan(), selected_action=action(title="Different"))


def test_result_converts_collections_and_copies_metadata():
    metadata = {"nested": [1]}
    result = ExecutionResult(reasoning=["reason"], errors=["error"], metadata=metadata)
    metadata["nested"].append(2)
    assert result.reasoning == ("reason",)
    assert result.errors == ("error",)
    assert result.metadata == {"nested": [1]}


def test_result_is_immutable():
    with pytest.raises(FrozenInstanceError):
        ExecutionResult().success = True


def test_result_equality_and_hash():
    assert ExecutionResult() == ExecutionResult()
    assert hash(ExecutionResult()) == hash(ExecutionResult())


@pytest.mark.parametrize("model", [parameter(), action(), plan(), ExecutionResult(execution_plan=plan())])
def test_models_serialize_with_asdict(model):
    assert isinstance(asdict(model), dict)


def test_public_imports_are_available():
    import app.services.diagnostic_engine as public

    for name in (
        "ExecutionStatus", "ExecutionTarget", "ExecutionRisk", "ExecutionParameter",
        "ExecutionAction", "ExecutionPlan", "ExecutionResult",
    ):
        assert getattr(public, name) is globals()[name]


def test_repr_is_deterministic():
    assert repr(plan()) == repr(plan())
    assert "0x" not in repr(plan())


def test_inputs_are_not_mutated():
    source_actions = [action()]
    source_errors = ["error"]
    plan(actions=source_actions, current_action_id="action-1", errors=source_errors)
    assert source_actions == [action()]
    assert source_errors == ["error"]


def test_files_are_utf8_without_bom():
    root = Path(__file__).parents[3]
    paths = (
        root / "app/services/diagnostic_engine/execution_models.py",
        root / "app/services/diagnostic_engine/__init__.py",
        Path(__file__),
    )
    for path in paths:
        content = path.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
