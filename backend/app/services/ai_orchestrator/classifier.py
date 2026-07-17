from dataclasses import dataclass

from app.models.ai_orchestrator import AIPriority


@dataclass(frozen=True)
class HypothesisDraft:
    code: str
    title: str
    description: str
    probability: float


@dataclass(frozen=True)
class ClassificationResult:
    category: str
    priority: AIPriority
    confidence: float
    hypotheses: list[HypothesisDraft]


def classify_incident(message: str) -> ClassificationResult:
    text = message.lower()
    if any(term in text for term in ["caixas", "servidor", "sql", "conexao", "conexão", "porta 1433"]):
        return ClassificationResult(
            category="NETWORK_SERVER",
            priority=AIPriority.HIGH,
            confidence=0.91,
            hypotheses=[
                HypothesisDraft("database_service_stopped", "Servico do banco de dados parado", "O SQL Server pode estar parado no servidor.", 0.65),
                HypothesisDraft("database_port_blocked", "Porta do banco bloqueada", "A porta 1433 pode estar indisponivel para os caixas.", 0.23),
                HypothesisDraft("dns_failure", "Falha de DNS", "Os caixas podem nao estar resolvendo o nome do servidor.", 0.12),
            ],
        )
    if any(term in text for term in ["impressora", "imprime", "printer"]):
        return ClassificationResult(
            category="PRINTER",
            priority=AIPriority.MEDIUM,
            confidence=0.82,
            hypotheses=[HypothesisDraft("printer_offline", "Impressora offline", "A impressora pode estar indisponivel ou desconectada.", 0.72)],
        )
    return ClassificationResult(
        category="GENERAL_SUPPORT",
        priority=AIPriority.LOW,
        confidence=0.7,
        hypotheses=[HypothesisDraft("unknown_failure", "Falha ainda nao identificada", "Sao necessarias verificacoes iniciais para classificar melhor.", 0.55)],
    )
