from app.models.ai_orchestrator import AISessionStatus


class InvalidStateTransition(ValueError):
    pass


VALID_TRANSITIONS: dict[AISessionStatus, set[AISessionStatus]] = {
    AISessionStatus.RECEIVED: {AISessionStatus.CLASSIFYING, AISessionStatus.CANCELLED},
    AISessionStatus.CLASSIFYING: {AISessionStatus.PLANNING, AISessionStatus.FAILED},
    AISessionStatus.PLANNING: {AISessionStatus.READY, AISessionStatus.FAILED},
    AISessionStatus.READY: {AISessionStatus.RUNNING, AISessionStatus.CANCELLED},
    AISessionStatus.RUNNING: {AISessionStatus.WAITING_TOOL, AISessionStatus.WAITING_APPROVAL, AISessionStatus.FAILED, AISessionStatus.CANCELLED},
    AISessionStatus.WAITING_TOOL: {AISessionStatus.ANALYZING_RESULT, AISessionStatus.FAILED},
    AISessionStatus.ANALYZING_RESULT: {
        AISessionStatus.RUNNING,
        AISessionStatus.WAITING_APPROVAL,
        AISessionStatus.RESOLVED,
        AISessionStatus.ESCALATED,
        AISessionStatus.FAILED,
    },
    AISessionStatus.WAITING_APPROVAL: {AISessionStatus.RUNNING, AISessionStatus.ESCALATED, AISessionStatus.CANCELLED},
    AISessionStatus.RESOLVED: set(),
    AISessionStatus.ESCALATED: set(),
    AISessionStatus.FAILED: set(),
    AISessionStatus.CANCELLED: set(),
}


def assert_transition(current: AISessionStatus | str, target: AISessionStatus) -> None:
    source = AISessionStatus(current)
    if target not in VALID_TRANSITIONS[source]:
        raise InvalidStateTransition(f"Invalid AI session transition: {source.value} -> {target.value}")
