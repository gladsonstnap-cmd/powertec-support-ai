from dataclasses import dataclass

from app.models.ai_orchestrator import AIPlanStep, AIPlanStepStatus, AIHypothesis
from app.services.ai_orchestrator.hypothesis_engine import strongest_hypothesis


@dataclass(frozen=True)
class OrchestratorDecision:
    decision: str
    reason: str
    confidence: float
    next_hypothesis: str | None = None
    recommended_tool: str | None = None


def decide_next(hypotheses: list[AIHypothesis], steps: list[AIPlanStep], max_steps: int, executed_steps: int) -> OrchestratorDecision:
    codes = {code for step in steps for code in step.result.get("evidence_codes", [])}
    pending = [step for step in steps if step.status in {AIPlanStepStatus.PENDING.value, AIPlanStepStatus.APPROVED.value}]
    waiting = next((step for step in steps if step.status == AIPlanStepStatus.WAITING_APPROVAL.value), None)
    strongest = strongest_hypothesis(hypotheses)
    if waiting is not None:
        return OrchestratorDecision("WAIT_APPROVAL", f"A etapa {waiting.tool_name} exige aprovacao antes da execucao simulada.", strongest.probability if strongest else 0.5, strongest.code if strongest else None, waiting.tool_name)
    if "SERVICE_RESTARTED" in codes and ("SERVICE_RUNNING" in codes or "DB_PORT_OPEN" in codes):
        return OrchestratorDecision("RESOLVE", "A causa foi sustentada por evidencias e uma verificacao posterior confirmou normalizacao simulada.", strongest.probability if strongest else 0.85, strongest.code if strongest else None)
    if "DNS_FAILED" in codes and not pending:
        return OrchestratorDecision("ESCALATE", "Falha de DNS confirmada, mas nao ha ferramenta segura de correcao nesta sprint.", strongest.probability if strongest else 0.8, "dns_failure")
    if "DB_PORT_CLOSED" in codes and "SERVICE_RUNNING" in codes:
        return OrchestratorDecision("ESCALATE", "Porta 1433 indisponivel com servico ativo indica restricao de rede/firewall.", strongest.probability if strongest else 0.75, "database_port_blocked")
    if "PRINTER_OFFLINE" in codes:
        return OrchestratorDecision("ESCALATE", "Impressora offline exige verificacao fisica ou ferramenta segura futura.", strongest.probability if strongest else 0.75, "printer_offline")
    if executed_steps >= max_steps:
        return OrchestratorDecision("ESCALATE", "Limite de etapas atingido sem conclusao segura.", strongest.probability if strongest else 0.5, strongest.code if strongest else None)
    if pending:
        return OrchestratorDecision("CONTINUE", "Ainda ha etapas seguras pendentes para diferenciar as hipoteses.", strongest.probability if strongest else 0.5, strongest.code if strongest else None, pending[0].tool_name)
    return OrchestratorDecision("ESCALATE", "Hipoteses permaneceram inconclusivas sem ferramenta segura adicional.", strongest.probability if strongest else 0.5, strongest.code if strongest else None)
