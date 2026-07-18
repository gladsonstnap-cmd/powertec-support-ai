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
    secondary_category: str | None
    priority: AIPriority
    confidence: float
    hypotheses: list[HypothesisDraft]


def classify_incident(message: str) -> ClassificationResult:
    text = message.lower()
    if any(term in text for term in ["sql server nao inicia", "sql server não inicia", "sql nao inicia", "sql não inicia", "mssql"]):
        return ClassificationResult(
            "DATABASE",
            "WINDOWS_SERVICE",
            AIPriority.HIGH,
            0.9,
            [
                HypothesisDraft("database_service_stopped", "Servico do banco de dados parado", "O servico SQL Server pode nao estar iniciado.", 0.55),
                HypothesisDraft("database_port_blocked", "Porta do banco bloqueada", "A porta 1433 pode estar indisponivel mesmo com o servico ativo.", 0.25),
                HypothesisDraft("application_misconfiguration", "Configuracao da aplicacao incorreta", "A aplicacao pode apontar para instancia ou host incorreto.", 0.20),
            ],
        )
    if any(term in text for term in ["disco", "c:", "espaco", "espaço", "armazenamento", "hd cheio"]):
        return ClassificationResult(
            "DISK_STORAGE",
            None,
            AIPriority.MEDIUM,
            0.87,
            [
                HypothesisDraft("disk_low_space", "Disco com pouco espaco", "O volume principal pode estar sem espaco operacional.", 0.74),
                HypothesisDraft("application_log_growth", "Crescimento de logs", "Logs podem estar ocupando espaco alem do esperado.", 0.26),
            ],
        )
    if any(term in text for term in ["nao resolve", "não resolve", "nome do servidor", "dns"]):
        return ClassificationResult(
            "DNS",
            "NETWORK_SERVER",
            AIPriority.HIGH,
            0.88,
            [
                HypothesisDraft("dns_failure", "Falha de DNS", "O nome do servidor pode nao resolver corretamente.", 0.65),
                HypothesisDraft("server_unreachable", "Servidor inacessivel", "O servidor pode estar indisponivel na rede.", 0.20),
                HypothesisDraft("database_port_blocked", "Porta do banco bloqueada", "A conectividade geral pode existir, mas a porta de banco falhar.", 0.15),
            ],
        )
    if any(term in text for term in ["caixas", "servidor", "sql", "conexao", "conexão", "porta 1433"]):
        return ClassificationResult(
            "NETWORK_SERVER",
            "DATABASE",
            AIPriority.HIGH,
            0.91,
            [
                HypothesisDraft("database_service_stopped", "Servico do banco de dados parado", "O SQL Server pode estar parado no servidor.", 0.40),
                HypothesisDraft("database_port_blocked", "Porta do banco bloqueada", "A porta 1433 pode estar indisponivel para os caixas.", 0.25),
                HypothesisDraft("dns_failure", "Falha de DNS", "Os caixas podem nao estar resolvendo o nome do servidor.", 0.20),
                HypothesisDraft("server_unreachable", "Servidor inacessivel", "O servidor pode nao responder na rede.", 0.15),
            ],
        )
    if any(term in text for term in ["impressora", "imprime", "printer", "cupom"]):
        return ClassificationResult(
            "PRINTING",
            None,
            AIPriority.MEDIUM,
            0.82,
            [
                HypothesisDraft("printer_offline", "Impressora offline", "A impressora pode estar indisponivel ou desconectada.", 0.72),
                HypothesisDraft("printer_spooler_stopped", "Spooler de impressao parado", "A fila de impressao pode estar parada.", 0.28),
            ],
        )
    return ClassificationResult(
        "UNKNOWN" if "?" not in text and len(text.strip()) < 12 else "GENERAL_SUPPORT",
        None,
        AIPriority.LOW,
        0.7,
        [HypothesisDraft("unknown_failure", "Falha ainda nao identificada", "Sao necessarias verificacoes iniciais para classificar melhor.", 0.55)],
    )
