from dataclasses import dataclass
from typing import Callable

from app.models.ai_orchestrator import AIRiskLevel


class ToolValidationError(ValueError):
    pass


ToolExecutor = Callable[[dict], dict]

DANGEROUS_KEYS = {"command", "shell", "powershell", "cmd", "bash", "script", "eval", "executable"}
ALLOWED_SCENARIOS = {
    "healthy",
    "sql_service_stopped",
    "dns_failure",
    "port_blocked",
    "disk_low_space",
    "printer_offline",
    "unknown_failure",
    "server_unreachable",
    "sql_service_running_but_port_blocked",
    "printer_spooler_stopped",
    "low_disk_after_cleanup",
    "conflicting_evidence",
}


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    allowed_parameters: set[str]
    risk_level: AIRiskLevel
    requires_approval: bool
    executor: ToolExecutor
    supported_categories: set[str]
    confirms_hypotheses: set[str]
    rejects_hypotheses: set[str]
    evidence_codes: set[str]
    estimated_cost: int = 1
    diagnostic_value: int = 1
    can_repeat: bool = False


def _scenario(parameters: dict) -> str:
    value = str(parameters.get("scenario", "healthy"))
    if value not in ALLOWED_SCENARIOS:
        raise ToolValidationError("Invalid simulation scenario.")
    return value


def _standard(tool_name: str, success: bool, evidence: dict, message: str) -> dict:
    return {
        "tool_name": tool_name,
        "success": success,
        "message": message,
        "evidence": evidence,
        "data": evidence,
        "evidence_codes": evidence.get("evidence_codes", []),
        "simulation": True,
    }


def _system_inventory(parameters: dict) -> dict:
    return _standard("system.inventory", True, {"os": "Windows Server simulado", "hostname": "servidor", "evidence_codes": ["INVENTORY_COLLECTED"]}, "Inventario simulado coletado.")


def _network_ping(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    reachable = scenario != "server_unreachable"
    return _standard(
        "network.ping",
        True,
        {"reachable": reachable, "latency_ms": 12 if reachable else None, "evidence_codes": ["SERVER_REACHABLE" if reachable else "SERVER_UNREACHABLE"]},
        "Servidor alcancavel no cenario simulado." if reachable else "Servidor inacessivel no cenario simulado.",
    )


def _network_dns_lookup(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    resolved = scenario != "dns_failure"
    return _standard(
        "network.dns_lookup",
        True,
        {"resolved": resolved, "address": "10.0.0.10" if resolved else None, "evidence_codes": ["DNS_RESOLVED" if resolved else "DNS_FAILED"]},
        "DNS simulado resolvido." if resolved else "Falha simulada de DNS.",
    )


def _network_test_port(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    open_port = scenario not in {"sql_service_stopped", "port_blocked", "sql_service_running_but_port_blocked"}
    return _standard(
        "network.test_port",
        True,
        {"port": parameters.get("port"), "open": open_port, "evidence_codes": ["DB_PORT_OPEN" if open_port else "DB_PORT_CLOSED"]},
        "Porta simulada aberta." if open_port else "Porta simulada indisponivel.",
    )


def _service_status(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    running = scenario not in {"sql_service_stopped", "printer_spooler_stopped"}
    if scenario == "conflicting_evidence":
        running = False
    return _standard(
        "windows.service_status",
        True,
        {"service_name": parameters.get("service_name"), "status": "running" if running else "stopped", "evidence_codes": ["SERVICE_RUNNING" if running else "SERVICE_STOPPED"]},
        "Servico simulado em execucao." if running else "Servico simulado parado.",
    )


def _event_logs(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    return _standard("windows.event_logs", True, {"events": [f"Evento simulado para {scenario}"], "evidence_codes": ["EVENT_LOGS_READ"]}, "Eventos simulados consultados.")


def _printer_list(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    online = scenario != "printer_offline"
    return _standard(
        "printer.list",
        True,
        {"printers": [{"name": "Impressora Fiscal", "online": online}], "evidence_codes": ["PRINTER_ONLINE" if online else "PRINTER_OFFLINE"]},
        "Impressoras simuladas consultadas.",
    )


def _disk_health(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    free = 18 if scenario == "low_disk_after_cleanup" else (4 if scenario == "disk_low_space" else 62)
    return _standard(
        "disk.health",
        True,
        {"free_percent": free, "evidence_codes": ["DISK_OK" if free >= 15 else "DISK_LOW_SPACE"]},
        "Disco simulado saudavel." if free >= 15 else "Pouco espaco em disco simulado.",
    )


def _knowledge_search(parameters: dict) -> dict:
    return _standard("knowledge.search", True, {"articles": ["KB-SQL-001", "KB-NET-002"], "evidence_codes": ["KNOWLEDGE_FOUND"]}, "Busca simulada concluida.")


def _service_restart(parameters: dict) -> dict:
    return _standard(
        "windows.service_restart",
        True,
        {"service_name": parameters.get("service_name"), "restarted": True, "status": "running", "evidence_codes": ["SERVICE_RESTARTED"]},
        "Reinicio simulado concluido; nenhum comando real foi executado.",
    )


TOOLS: dict[str, ToolDefinition] = {
    "system.inventory": ToolDefinition("system.inventory", "Inventario simulado do sistema.", {"scenario"}, AIRiskLevel.READ_ONLY, False, _system_inventory, {"GENERAL_SUPPORT", "UNKNOWN"}, set(), set(), {"INVENTORY_COLLECTED"}),
    "network.ping": ToolDefinition("network.ping", "Ping simulado.", {"host", "scenario"}, AIRiskLevel.READ_ONLY, False, _network_ping, {"NETWORK_SERVER", "DNS"}, {"server_unreachable"}, {"server_unreachable"}, {"SERVER_REACHABLE", "SERVER_UNREACHABLE"}, 1, 5),
    "network.dns_lookup": ToolDefinition("network.dns_lookup", "DNS lookup simulado.", {"hostname", "scenario"}, AIRiskLevel.READ_ONLY, False, _network_dns_lookup, {"NETWORK_SERVER", "DNS"}, {"dns_failure"}, {"dns_failure"}, {"DNS_RESOLVED", "DNS_FAILED"}, 1, 5),
    "network.test_port": ToolDefinition("network.test_port", "Teste simulado de porta.", {"host", "port", "scenario"}, AIRiskLevel.READ_ONLY, False, _network_test_port, {"NETWORK_SERVER", "DATABASE"}, {"database_port_blocked", "database_service_stopped"}, {"database_port_blocked"}, {"DB_PORT_OPEN", "DB_PORT_CLOSED"}, 1, 5, True),
    "windows.service_status": ToolDefinition("windows.service_status", "Status simulado de servico Windows.", {"service_name", "scenario"}, AIRiskLevel.READ_ONLY, False, _service_status, {"NETWORK_SERVER", "DATABASE", "WINDOWS_SERVICE", "PRINTING"}, {"database_service_stopped", "printer_spooler_stopped"}, {"database_service_stopped"}, {"SERVICE_RUNNING", "SERVICE_STOPPED"}, 1, 5, True),
    "windows.event_logs": ToolDefinition("windows.event_logs", "Eventos Windows simulados.", {"source", "scenario"}, AIRiskLevel.READ_ONLY, False, _event_logs, {"PRINTING", "DISK_STORAGE", "APPLICATION"}, set(), set(), {"EVENT_LOGS_READ"}),
    "printer.list": ToolDefinition("printer.list", "Listagem simulada de impressoras.", {"scenario"}, AIRiskLevel.READ_ONLY, False, _printer_list, {"PRINTING"}, {"printer_offline"}, {"printer_offline"}, {"PRINTER_ONLINE", "PRINTER_OFFLINE"}, 1, 5),
    "disk.health": ToolDefinition("disk.health", "Saude simulada do disco.", {"scenario"}, AIRiskLevel.READ_ONLY, False, _disk_health, {"DISK_STORAGE"}, {"disk_low_space"}, {"disk_low_space"}, {"DISK_OK", "DISK_LOW_SPACE"}, 1, 5, True),
    "knowledge.search": ToolDefinition("knowledge.search", "Busca simulada na base de conhecimento.", {"query", "scenario"}, AIRiskLevel.READ_ONLY, False, _knowledge_search, {"GENERAL_SUPPORT", "APPLICATION"}, set(), set(), {"KNOWLEDGE_FOUND"}),
    "windows.service_restart": ToolDefinition("windows.service_restart", "Reinicio simulado de servico Windows.", {"service_name", "scenario"}, AIRiskLevel.SAFE_ACTION, True, _service_restart, {"NETWORK_SERVER", "DATABASE", "WINDOWS_SERVICE"}, {"database_service_stopped"}, set(), {"SERVICE_RESTARTED"}, 2, 4),
}


def _reject_dangerous_keys(parameters: dict) -> None:
    for key, value in parameters.items():
        if key.lower() in DANGEROUS_KEYS:
            raise ToolValidationError(f"Dangerous parameter rejected: {key}")
        if isinstance(value, dict):
            _reject_dangerous_keys(value)


def get_tool(name: str) -> ToolDefinition:
    try:
        return TOOLS[name]
    except KeyError as exc:
        raise ToolValidationError(f"Unknown tool: {name}") from exc


def validate_parameters(tool: ToolDefinition, parameters: dict) -> None:
    _reject_dangerous_keys(parameters)
    extra = set(parameters) - tool.allowed_parameters
    if extra:
        raise ToolValidationError(f"Unsupported parameters for {tool.name}: {', '.join(sorted(extra))}")
    if "scenario" in parameters:
        _scenario(parameters)


def execute_tool(name: str, parameters: dict) -> dict:
    tool = get_tool(name)
    validate_parameters(tool, parameters)
    return tool.executor(parameters)
