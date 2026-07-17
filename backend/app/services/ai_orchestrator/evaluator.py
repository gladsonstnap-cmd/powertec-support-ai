from app.models.ai_orchestrator import AIPlanStepStatus


def has_resolution_evidence(step_results: list[dict]) -> bool:
    return any(result.get("success") is True and bool(result.get("evidence")) for result in step_results)


def should_escalate_after_failures(consecutive_failures: int, threshold: int) -> bool:
    return consecutive_failures >= threshold


def completed_result_from_step_status(status: str, result: dict) -> dict | None:
    if status == AIPlanStepStatus.COMPLETED.value:
        return result
    return None
