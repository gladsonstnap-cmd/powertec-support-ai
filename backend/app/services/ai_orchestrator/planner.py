from dataclasses import dataclass

from app.models.ai_orchestrator import AIRiskLevel
from app.services.ai_orchestrator.classifier import ClassificationResult


@dataclass(frozen=True)
class PlanStepDraft:
    sequence: int
    tool_name: str
    title: str
    description: str
    parameters: dict
    risk_level: AIRiskLevel
    requires_approval: bool
    selection_reason: str = "Etapa inicial segura e de alto valor diagnostico."
    is_dynamic: bool = False


def build_plan(classification: ClassificationResult, scenario: str) -> list[PlanStepDraft]:
    if classification.category == "NETWORK_SERVER":
        return [
            PlanStepDraft(1, "network.ping", "Verificar conectividade", "Simula ping ate o servidor informado.", {"host": "servidor", "scenario": scenario}, AIRiskLevel.READ_ONLY, False),
            PlanStepDraft(2, "network.dns_lookup", "Validar DNS", "Simula resolucao do nome do servidor.", {"hostname": "servidor", "scenario": scenario}, AIRiskLevel.READ_ONLY, False),
            PlanStepDraft(3, "network.test_port", "Testar porta SQL", "Simula teste da porta 1433 usada pelo SQL Server.", {"host": "servidor", "port": 1433, "scenario": scenario}, AIRiskLevel.READ_ONLY, False),
            PlanStepDraft(4, "windows.service_status", "Verificar SQL Server", "Simula consulta de status do servico SQL Server.", {"service_name": "MSSQLSERVER", "scenario": scenario}, AIRiskLevel.READ_ONLY, False),
        ]
    if classification.category in {"DATABASE", "WINDOWS_SERVICE"}:
        return [
            PlanStepDraft(1, "windows.service_status", "Verificar SQL Server", "Simula consulta de status do servico SQL Server.", {"service_name": "MSSQLSERVER", "scenario": scenario}, AIRiskLevel.READ_ONLY, False),
            PlanStepDraft(2, "network.test_port", "Testar porta SQL", "Simula teste da porta 1433 usada pelo SQL Server.", {"host": "servidor", "port": 1433, "scenario": scenario}, AIRiskLevel.READ_ONLY, False),
        ]
    if classification.category == "DNS":
        return [
            PlanStepDraft(1, "network.ping", "Verificar servidor por IP", "Simula conectividade direta ao servidor.", {"host": "10.0.0.10", "scenario": "healthy"}, AIRiskLevel.READ_ONLY, False),
            PlanStepDraft(2, "network.dns_lookup", "Validar DNS", "Simula resolucao do nome do servidor.", {"hostname": "servidor", "scenario": scenario}, AIRiskLevel.READ_ONLY, False),
        ]
    if classification.category == "PRINTING":
        return [
            PlanStepDraft(1, "printer.list", "Listar impressoras", "Simula consulta de impressoras configuradas.", {"scenario": scenario}, AIRiskLevel.READ_ONLY, False),
            PlanStepDraft(2, "windows.event_logs", "Verificar eventos", "Simula leitura de eventos relacionados a impressao.", {"source": "print", "scenario": scenario}, AIRiskLevel.READ_ONLY, False),
        ]
    if classification.category == "DISK_STORAGE":
        return [
            PlanStepDraft(1, "disk.health", "Verificar espaco em disco", "Simula consulta de saude e espaco do disco.", {"scenario": scenario}, AIRiskLevel.READ_ONLY, False),
            PlanStepDraft(2, "windows.event_logs", "Verificar eventos de armazenamento", "Simula leitura de eventos relacionados ao disco.", {"source": "disk", "scenario": scenario}, AIRiskLevel.READ_ONLY, False),
        ]
    return [
        PlanStepDraft(1, "system.inventory", "Coletar inventario", "Simula coleta basica de inventario do ambiente.", {"scenario": scenario}, AIRiskLevel.READ_ONLY, False),
        PlanStepDraft(2, "knowledge.search", "Consultar base de conhecimento", "Simula busca por artigos internos relevantes.", {"query": classification.category, "scenario": scenario}, AIRiskLevel.READ_ONLY, False),
    ]


def dynamic_step(sequence: int, tool_name: str, scenario: str, reason: str) -> PlanStepDraft:
    if tool_name == "windows.service_restart":
        return PlanStepDraft(
            sequence,
            "windows.service_restart",
            "Reiniciar SQL Server",
            "Simula reinicio seguro do servico SQL Server apos aprovacao.",
            {"service_name": "MSSQLSERVER", "scenario": scenario},
            AIRiskLevel.SAFE_ACTION,
            True,
            reason,
            True,
        )
    if tool_name == "network.test_port":
        return PlanStepDraft(
            sequence,
            "network.test_port",
            "Confirmar porta SQL apos acao",
            "Simula verificacao posterior da porta 1433.",
            {"host": "servidor", "port": 1433, "scenario": "healthy"},
            AIRiskLevel.READ_ONLY,
            False,
            reason,
            True,
        )
    return PlanStepDraft(
        sequence,
        "windows.service_status",
        "Confirmar SQL Server ativo",
        "Simula verificacao posterior do servico SQL Server.",
        {"service_name": "MSSQLSERVER", "scenario": "healthy"},
        AIRiskLevel.READ_ONLY,
        False,
        reason,
        True,
    )
