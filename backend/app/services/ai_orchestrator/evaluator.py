from dataclasses import dataclass

from app.models.ai_orchestrator import AIPlanStepStatus


@dataclass(frozen=True)
class EvidenceResult:
    evidence_codes: list[str]
    summary: str
    conclusive: bool
    needs_followup: bool


def evaluate_tool_result(tool_name: str, result: dict) -> EvidenceResult:
    evidence_codes = [str(code) for code in result.get("evidence_codes", [])]
    evidence = result.get("evidence", {})
    conclusive_codes = {"DNS_FAILED", "SERVICE_STOPPED", "SERVICE_RUNNING", "PRINTER_OFFLINE", "DISK_LOW_SPACE", "DB_PORT_OPEN"}
    needs_followup = tool_name == "windows.service_restart"
    summary = str(result.get("message") or "Resultado simulado avaliado.")
    if evidence:
        summary = f"{summary} Evidencias: {', '.join(evidence_codes) or 'sem codigo especifico'}."
    return EvidenceResult(evidence_codes, summary, any(code in conclusive_codes for code in evidence_codes), needs_followup)


def has_resolution_evidence(step_results: list[dict]) -> bool:
    codes = {code for result in step_results for code in result.get("evidence_codes", [])}
    return "SERVICE_RESTARTED" in codes and ("SERVICE_RUNNING" in codes or "DB_PORT_OPEN" in codes)


def should_escalate_after_failures(consecutive_failures: int, threshold: int) -> bool:
    return consecutive_failures >= threshold


def completed_result_from_step_status(status: str, result: dict) -> dict | None:
    if status == AIPlanStepStatus.COMPLETED.value:
        return result
    return None
