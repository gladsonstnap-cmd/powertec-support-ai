from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from app.services.diagnostic_engine import (
    ActionApprovalRequest,
    ApprovalActor,
    ApprovalDecision,
    ApprovalResult,
    ApprovalScope,
    ApprovalStatus,
    ApprovalType,
    ApprovedActionGrant,
)
from app.services.diagnostic_engine.execution_models import (
    ExecutionAction,
    ExecutionRisk,
    ExecutionStatus,
    ExecutionTarget,
)


def actor(**overrides):
    values = {
        "actor_id": "actor-1",
        "actor_type": ApprovalType.HUMAN_TECHNICIAN,
        "display_name": "Técnico",
    }
    values.update(overrides)
    return ApprovalActor(**values)


def action(action_id="action-1", **overrides):
    values = {
        "action_id": action_id,
        "action_name": "check_service_status",
        "title": "Verificar serviço",
        "description": "Descrição somente; nada foi executado.",
        "target": ExecutionTarget.WINDOWS,
        "status": ExecutionStatus.BLOCKED,
        "risk": ExecutionRisk.MEDIUM,
        "parameters": (),
        "timeout_seconds": 30,
        "requires_confirmation": True,
        "requires_human": False,
    }
    values.update(overrides)
    return ExecutionAction(**values)


def request(**overrides):
    values = {
        "approval_id": "approval-1",
        "scope": ApprovalScope.SINGLE_ACTION,
        "execution_plan_id": "execution-plan-1",
        "action_id": "action-1",
        "session_id": "session-1",
        "requested_by": actor(),
        "required_actor_type": ApprovalType.HUMAN_TECHNICIAN,
        "status": ApprovalStatus.PENDING,
        "risk": ExecutionRisk.MEDIUM,
        "action_snapshot": action(),
        "reason": "Confirmação necessária",
        "created_at_monotonic": 10.0,
        "expires_at_monotonic": 20.0,
    }
    values.update(overrides)
    return ActionApprovalRequest(**values)


def decision(**overrides):
    values = {
        "approval_id": "approval-1",
        "status": ApprovalStatus.APPROVED,
        "decided_by": actor(),
        "decided_at_monotonic": 11.0,
        "reason": "Aprovado explicitamente",
    }
    values.update(overrides)
    return ApprovalDecision(**values)


def grant(**overrides):
    values = {
        "grant_id": "grant-1",
        "approval_id": "approval-1",
        "execution_plan_id": "execution-plan-1",
        "action_id": "action-1",
        "action_snapshot": action(),
        "approved_by": actor(),
        "approved_at_monotonic": 11.0,
        "expires_at_monotonic": 20.0,
    }
    values.update(overrides)
    return ApprovedActionGrant(**values)


@pytest.mark.parametrize("enum_type", [ApprovalStatus, ApprovalType, ApprovalScope])
def test_enums_are_string_enums(enum_type):
    assert all(isinstance(item, str) and item.value == item.name for item in enum_type)


@pytest.mark.parametrize("member", list(ApprovalStatus))
def test_approval_status_members_are_stable(member):
    assert ApprovalStatus(member.value) is member


@pytest.mark.parametrize("member", list(ApprovalType))
def test_approval_type_members_are_stable(member):
    assert ApprovalType(member.value) is member


@pytest.mark.parametrize("member", list(ApprovalScope))
def test_approval_scope_members_are_stable(member):
    assert ApprovalScope(member.value) is member


def test_actor_creation_and_defaults():
    item = ApprovalActor("actor-1", ApprovalType.USER_CONFIRMATION)
    assert item.display_name is None and item.metadata == {}


@pytest.mark.parametrize("actor_id", ["", "   ", None])
def test_actor_rejects_empty_id(actor_id):
    with pytest.raises(ValueError, match="actor_id"):
        actor(actor_id=actor_id)


def test_actor_rejects_invalid_type():
    with pytest.raises(ValueError, match="actor_type"):
        actor(actor_type="HUMAN_TECHNICIAN")


def test_actor_is_immutable_equal_and_hashable():
    assert actor() == actor()
    assert hash(actor()) == hash(actor())
    with pytest.raises(FrozenInstanceError):
        actor().actor_id = "changed"


def test_actor_metadata_is_defensively_copied():
    metadata = {"nested": [1]}
    item = actor(metadata=metadata)
    metadata["nested"].append(2)
    assert item.metadata == {"nested": [1]}


@pytest.mark.parametrize("secret", [
    {"password": "value"}, {"senha": "value"}, {"token": "value"},
    {"secret": "value"}, {"credential": "value"}, {"nested": {"token": "value"}},
])
def test_actor_rejects_secret_metadata(secret):
    with pytest.raises(ValueError, match="metadata"):
        actor(metadata=secret)


def test_request_creation():
    item = request()
    assert item.status == ApprovalStatus.PENDING
    assert item.action_snapshot == action()


@pytest.mark.parametrize(("field", "value"), [
    ("approval_id", ""), ("approval_id", "  "),
    ("execution_plan_id", ""), ("execution_plan_id", None),
])
def test_request_rejects_required_empty_ids(field, value):
    with pytest.raises(ValueError, match=field):
        request(**{field: value})


@pytest.mark.parametrize("scope", [ApprovalScope.EXECUTION_PLAN, ApprovalScope.SESSION])
def test_non_action_scopes_allow_no_action_id(scope):
    assert request(scope=scope, action_id=None, action_snapshot=None).action_id is None


def test_single_action_requires_action_id():
    with pytest.raises(ValueError, match="action_id"):
        request(action_id=None, action_snapshot=None)


def test_request_rejects_mismatched_snapshot():
    with pytest.raises(ValueError, match="action_snapshot"):
        request(action_snapshot=action("other"))


@pytest.mark.parametrize("expires", [9.9, -1.0])
def test_request_rejects_expiration_before_creation(expires):
    with pytest.raises(ValueError, match="expires_at_monotonic"):
        request(expires_at_monotonic=expires)


@pytest.mark.parametrize("expires", [10.0, 20.0, None])
def test_request_accepts_valid_expiration(expires):
    assert request(expires_at_monotonic=expires).expires_at_monotonic == expires


@pytest.mark.parametrize("value", [True, "10", None])
def test_request_rejects_invalid_created_timestamp(value):
    with pytest.raises(ValueError, match="created_at_monotonic"):
        request(created_at_monotonic=value)


@pytest.mark.parametrize(("field", "value"), [
    ("scope", "SINGLE_ACTION"), ("required_actor_type", "ADMINISTRATOR"),
    ("status", "PENDING"), ("risk", "MEDIUM"),
])
def test_request_rejects_invalid_enum_types(field, value):
    with pytest.raises(ValueError, match=field):
        request(**{field: value})


def test_approved_request_does_not_change_action_status():
    item = request(status=ApprovalStatus.APPROVED)
    assert item.action_snapshot.status == ExecutionStatus.BLOCKED


def test_request_collections_are_defensive():
    errors = ["error"]
    metadata = {"nested": [1]}
    item = request(errors=errors, metadata=metadata)
    errors.append("other")
    metadata["nested"].append(2)
    assert item.errors == ("error",)
    assert item.metadata == {"nested": [1]}


def test_request_is_immutable_equal_and_hashable():
    assert request() == request()
    assert hash(request()) == hash(request())
    with pytest.raises(FrozenInstanceError):
        request().status = ApprovalStatus.APPROVED


@pytest.mark.parametrize("status", [
    ApprovalStatus.APPROVED, ApprovalStatus.REJECTED,
    ApprovalStatus.CANCELLED, ApprovalStatus.EXPIRED,
])
def test_decision_accepts_valid_terminal_status(status):
    assert decision(status=status).status == status


@pytest.mark.parametrize("status", [ApprovalStatus.PENDING, ApprovalStatus.USED])
def test_decision_rejects_invalid_status(status):
    with pytest.raises(ValueError, match="status"):
        decision(status=status)


def test_decision_rejects_string_status():
    with pytest.raises(ValueError, match="status"):
        decision(status="APPROVED")


@pytest.mark.parametrize("approval_id", ["", " ", None])
def test_decision_rejects_empty_id(approval_id):
    with pytest.raises(ValueError, match="approval_id"):
        decision(approval_id=approval_id)


@pytest.mark.parametrize("value", [True, "11", None])
def test_decision_rejects_invalid_timestamp(value):
    with pytest.raises(ValueError, match="decided_at_monotonic"):
        decision(decided_at_monotonic=value)


def test_decision_is_immutable_equal_hashable_and_defensive():
    metadata = {"nested": [1]}
    errors = ["error"]
    item = decision(metadata=metadata, errors=errors)
    metadata["nested"].append(2)
    errors.append("other")
    assert item.metadata == {"nested": [1]} and item.errors == ("error",)
    assert decision() == decision() and hash(decision()) == hash(decision())
    with pytest.raises(FrozenInstanceError):
        item.status = ApprovalStatus.REJECTED


@pytest.mark.parametrize(("field", "value"), [
    ("grant_id", ""), ("approval_id", ""),
    ("execution_plan_id", " "), ("action_id", None),
])
def test_grant_rejects_empty_ids(field, value):
    with pytest.raises(ValueError, match=field):
        grant(**{field: value})


def test_grant_rejects_mismatched_snapshot():
    with pytest.raises(ValueError, match="action_snapshot"):
        grant(action_snapshot=action("other"))


def test_grant_rejects_invalid_actor():
    with pytest.raises(ValueError, match="approved_by"):
        grant(approved_by=None)


@pytest.mark.parametrize("expires", [10.9, -1.0])
def test_grant_rejects_expiration_before_approval(expires):
    with pytest.raises(ValueError, match="expires_at_monotonic"):
        grant(expires_at_monotonic=expires)


@pytest.mark.parametrize("expires", [11.0, 20.0, None])
def test_grant_accepts_valid_expiration(expires):
    assert grant(expires_at_monotonic=expires).expires_at_monotonic == expires


@pytest.mark.parametrize("field", ["single_use", "used"])
def test_grant_rejects_non_boolean_flags(field):
    with pytest.raises(ValueError, match=field):
        grant(**{field: 1})


@pytest.mark.parametrize(("single_use", "used"), [(True, False), (True, True), (False, False), (False, True)])
def test_grant_supports_usage_states(single_use, used):
    item = grant(single_use=single_use, used=used)
    assert (item.single_use, item.used) == (single_use, used)
    assert item.action_snapshot.status == ExecutionStatus.BLOCKED


def test_grant_is_immutable_equal_hashable_and_defensive():
    metadata = {"nested": [1]}
    item = grant(metadata=metadata)
    metadata["nested"].append(2)
    assert item.metadata == {"nested": [1]}
    assert grant() == grant() and hash(grant()) == hash(grant())
    with pytest.raises(FrozenInstanceError):
        item.used = True


def test_result_creation_with_approved_grant():
    item = ApprovalResult(True, request(), decision(), grant())
    assert item.success and item.grant == grant()


def test_result_rejects_success_without_content():
    with pytest.raises(ValueError, match="coherent"):
        ApprovalResult(success=True)


@pytest.mark.parametrize("status", [ApprovalStatus.REJECTED, ApprovalStatus.CANCELLED, ApprovalStatus.EXPIRED])
def test_result_rejects_grant_without_approved_decision(status):
    with pytest.raises(ValueError, match="APPROVED"):
        ApprovalResult(decision=decision(status=status), grant=grant())


def test_result_rejects_grant_without_decision():
    with pytest.raises(ValueError, match="APPROVED"):
        ApprovalResult(grant=grant())


@pytest.mark.parametrize("component", ["request", "decision", "grant"])
def test_result_rejects_inconsistent_approval_id(component):
    values = {"request": request(), "decision": decision(), "grant": grant()}
    factory = {"request": request, "decision": decision, "grant": grant}[component]
    values[component] = factory(approval_id="other")
    with pytest.raises(ValueError, match="approval_id"):
        ApprovalResult(**values)


def test_result_collections_are_defensive_and_immutable():
    reasoning = ["approved explicitly"]
    errors = ["audit note"]
    metadata = {"nested": [1]}
    item = ApprovalResult(reasoning=reasoning, errors=errors, metadata=metadata)
    reasoning.append("other")
    errors.append("other")
    metadata["nested"].append(2)
    assert item.reasoning == ("approved explicitly",)
    assert item.errors == ("audit note",)
    assert item.metadata == {"nested": [1]}
    with pytest.raises(FrozenInstanceError):
        item.success = True


def test_result_equality_and_hash():
    first = ApprovalResult(True, request(), decision(), grant())
    second = ApprovalResult(True, request(), decision(), grant())
    assert first == second and hash(first) == hash(second)


@pytest.mark.parametrize("factory", [actor, request, decision, grant])
def test_all_metadata_models_reject_nested_secrets(factory):
    with pytest.raises(ValueError, match="metadata"):
        factory(metadata={"audit": [{"token": "hidden"}]})


def test_result_rejects_secret_metadata():
    with pytest.raises(ValueError, match="metadata"):
        ApprovalResult(metadata={"credential": "hidden"})


@pytest.mark.parametrize("model", [actor(), request(), decision(), grant(), ApprovalResult(request=request())])
def test_models_serialize_with_asdict(model):
    assert isinstance(asdict(model), dict)


def test_repr_is_deterministic():
    assert repr(ApprovalResult(request=request())) == repr(ApprovalResult(request=request()))
    assert "0x" not in repr(grant())


def test_public_imports_are_available():
    import app.services.diagnostic_engine as public

    for name in (
        "ApprovalStatus", "ApprovalType", "ApprovalScope", "ApprovalActor",
        "ActionApprovalRequest", "ApprovalDecision", "ApprovedActionGrant", "ApprovalResult",
    ):
        assert getattr(public, name) is globals()[name]


def test_approval_models_do_not_change_action_snapshot():
    original = action()
    snapshot = request(action_snapshot=original).action_snapshot
    assert original.status == snapshot.status == ExecutionStatus.BLOCKED


def test_files_are_utf8_without_bom():
    root = Path(__file__).parents[3]
    for path in (
        root / "app/services/diagnostic_engine/approval_models.py",
        root / "app/services/diagnostic_engine/__init__.py",
        Path(__file__),
    ):
        content = path.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf")
        content.decode("utf-8")
