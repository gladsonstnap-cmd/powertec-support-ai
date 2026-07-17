from dataclasses import dataclass
from typing import Callable

from app.models.ai_orchestrator import AIRiskLevel


class ToolValidationError(ValueError):
    pass


ToolExecutor = Callable[[dict], dict]

DANGEROUS_KEYS = {"command", "shell", "powershell", "cmd", "bash", "script", "eval", "executable"}
ALLOWED_SCENARIOS = {"healthy", "sql_service_stopped", "dns_failure", "port_blocked", "disk_low_space", "printer_offline", "unknown_failure"}


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    allowed_parameters: set[str]
    risk_level: AIRiskLevel
    requires_approval: bool
    executor: ToolExecutor


def _scenario(parameters: dict) -> str:
    value = str(parameters.get("scenario", "healthy"))
    if value not in ALLOWED_SCENARIOS:
        raise ToolValidationError("Invalid simulation scenario.")
    return value


def _standard(tool_name: str, success: bool, evidence: dict, message: str) -> dict:
    return {"tool_name": tool_name, "success": success, "message": message, "evidence": evidence, "simulation": True}


def _system_inventory(parameters: dict) -> dict:
    return _standard("system.inventory", True, {"os": "Windows Server simulado", "hostname": "servidor"}, "Inventario simulado coletado.")


def _network_ping(parameters: dict) -> dict:
    return _standard("network.ping", True, {"reachable": True, "latency_ms": 12}, "Servidor alcancavel no cenario simulado.")


def _network_dns_lookup(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    resolved = scenario != "dns_failure"
    return _standard("network.dns_lookup", True, {"resolved": resolved, "address": "10.0.0.10" if resolved else None}, "DNS simulado resolvido." if resolved else "Falha simulada de DNS.")


def _network_test_port(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    open_port = scenario not in {"sql_service_stopped", "port_blocked"}
    return _standard("network.test_port", True, {"port": parameters.get("port"), "open": open_port}, "Porta simulada aberta." if open_port else "Porta simulada indisponivel.")


def _service_status(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    running = scenario != "sql_service_stopped"
    return _standard("windows.service_status", True, {"service_name": parameters.get("service_name"), "status": "running" if running else "stopped"}, "Servico simulado em execucao." if running else "Servico simulado parado.")


def _event_logs(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    return _standard("windows.event_logs", True, {"events": [f"Evento simulado para {scenario}"]}, "Eventos simulados consultados.")


def _printer_list(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    online = scenario != "printer_offline"
    return _standard("printer.list", True, {"printers": [{"name": "Impressora Fiscal", "online": online}]}, "Impressoras simuladas consultadas.")


def _disk_health(parameters: dict) -> dict:
    scenario = _scenario(parameters)
    ok = scenario != "disk_low_space"
    return _standard("disk.health", True, {"free_percent": 4 if not ok else 62}, "Disco simulado saudavel." if ok else "Pouco espaco em disco simulado.")


def _knowledge_search(parameters: dict) -> dict:
    return _standard("knowledge.search", True, {"articles": ["KB-SQL-001", "KB-NET-002"]}, "Busca simulada concluida.")


def _service_restart(parameters: dict) -> dict:
    return _standard("windows.service_restart", True, {"service_name": parameters.get("service_name"), "restarted": True, "status": "running"}, "Reinicio simulado concluido; nenhum comando real foi executado.")


TOOLS: dict[str, ToolDefinition] = {
    "system.inventory": ToolDefinition("system.inventory", "Inventario simulado do sistema.", {"scenario"}, AIRiskLevel.READ_ONLY, False, _system_inventory),
    "network.ping": ToolDefinition("network.ping", "Ping simulado.", {"host", "scenario"}, AIRiskLevel.READ_ONLY, False, _network_ping),
    "network.dns_lookup": ToolDefinition("network.dns_lookup", "DNS lookup simulado.", {"hostname", "scenario"}, AIRiskLevel.READ_ONLY, False, _network_dns_lookup),
    "network.test_port": ToolDefinition("network.test_port", "Teste simulado de porta.", {"host", "port", "scenario"}, AIRiskLevel.READ_ONLY, False, _network_test_port),
    "windows.service_status": ToolDefinition("windows.service_status", "Status simulado de servico Windows.", {"service_name", "scenario"}, AIRiskLevel.READ_ONLY, False, _service_status),
    "windows.event_logs": ToolDefinition("windows.event_logs", "Eventos Windows simulados.", {"source", "scenario"}, AIRiskLevel.READ_ONLY, False, _event_logs),
    "printer.list": ToolDefinition("printer.list", "Listagem simulada de impressoras.", {"scenario"}, AIRiskLevel.READ_ONLY, False, _printer_list),
    "disk.health": ToolDefinition("disk.health", "Saude simulada do disco.", {"scenario"}, AIRiskLevel.READ_ONLY, False, _disk_health),
    "knowledge.search": ToolDefinition("knowledge.search", "Busca simulada na base de conhecimento.", {"query", "scenario"}, AIRiskLevel.READ_ONLY, False, _knowledge_search),
    "windows.service_restart": ToolDefinition("windows.service_restart", "Reinicio simulado de servico Windows.", {"service_name", "scenario"}, AIRiskLevel.SAFE_ACTION, True, _service_restart),
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
