from typing import Any

from agent.config import AgentConfig
from agent.models import RiskLevel, ToolDefinition
from agent.tools import disk_health_tool, event_logs_tool, network_test_tool, service_status_tool, system_info_tool


def windows_update_status(arguments: dict[str, Any], config: AgentConfig) -> dict[str, Any]:
    return {"status": "unknown", "pending_updates": None, "simulation": config.mode.value == "simulation"}


def _schema(properties: dict[str, dict], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


def build_registry(config: AgentConfig | None = None) -> dict[str, ToolDefinition]:
    return {
        "system_info": ToolDefinition("system_info", "Coleta inventario basico do sistema.", RiskLevel.READ_ONLY, False, ("Windows", "Linux", "Darwin"), 10, _schema({}), _schema({}), system_info_tool.execute),
        "disk_health": ToolDefinition("disk_health", "Coleta uso de disco sem SMART obrigatorio.", RiskLevel.READ_ONLY, False, ("Windows", "Linux", "Darwin"), 10, _schema({"path": {"type": "string", "maxLength": 120}}), _schema({}), disk_health_tool.execute),
        "network_test": ToolDefinition(
            "network_test",
            "Coleta rede local, DNS seguro ou TCP para destino permitido.",
            RiskLevel.READ_ONLY,
            False,
            ("Windows", "Linux", "Darwin"),
            10,
            _schema({"mode": {"type": "string", "enum": ["summary", "dns", "tcp"]}, "hostname": {"type": "string", "maxLength": 120}, "host": {"type": "string", "maxLength": 120}, "port": {"type": "integer", "minimum": 1, "maximum": 65535}}, ["mode"]),
            _schema({}),
            network_test_tool.execute,
        ),
        "service_status": ToolDefinition("service_status", "Consulta status de servico por nome seguro.", RiskLevel.READ_ONLY, False, ("Windows",), 10, _schema({"service_name": {"type": "string", "maxLength": 80}}, ["service_name"]), _schema({}), service_status_tool.execute),
        "event_logs": ToolDefinition("event_logs", "Coleta eventos recentes e sanitizados.", RiskLevel.READ_ONLY, False, ("Windows",), 10, _schema({"source": {"type": "string", "maxLength": 80}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}), _schema({}), event_logs_tool.execute),
        "windows_update_status": ToolDefinition("windows_update_status", "Consulta estado resumido do Windows Update.", RiskLevel.READ_ONLY, False, ("Windows",), 10, _schema({}), _schema({}), windows_update_status),
    }


def get_tool(name: str, config: AgentConfig | None = None) -> ToolDefinition:
    registry = build_registry(config)
    if name not in registry:
        raise KeyError(f"Unknown tool: {name}")
    return registry[name]
