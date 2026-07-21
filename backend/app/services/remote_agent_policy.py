import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any

PROHIBITED_TERMS = {
    "powershell",
    "powershell.exe",
    "pwsh",
    "cmd",
    "cmd.exe",
    "bash",
    "sh",
    "shell",
    "script",
    "eval",
    "exec",
    "invoke-expression",
    "encodedcommand",
    "downloadstring",
}


@dataclass(frozen=True)
class ServerTool:
    name: str
    description: str
    risk_level: str
    requires_approval: bool
    supported_platforms: tuple[str, ...]
    timeout_seconds: int
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


def make_agent_token() -> str:
    return secrets.token_urlsafe(32)


def hash_agent_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_agent_token(token: str, token_hash: str) -> bool:
    return secrets.compare_digest(hash_agent_token(token), token_hash)


def tool_schema(properties: dict[str, dict], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


SERVER_TOOL_REGISTRY = {
    "system_info": ServerTool("system_info", "Coleta inventario basico.", "read_only", False, ("Windows", "Linux", "Darwin"), 10, tool_schema({}), tool_schema({})),
    "disk_health": ServerTool("disk_health", "Coleta saude de disco.", "read_only", False, ("Windows", "Linux", "Darwin"), 10, tool_schema({"path": {"type": "string", "maxLength": 120}}), tool_schema({})),
    "network_test": ServerTool("network_test", "Executa teste seguro de rede.", "read_only", False, ("Windows", "Linux", "Darwin"), 10, tool_schema({"mode": {"type": "string", "enum": ["summary", "dns", "tcp"]}, "hostname": {"type": "string", "maxLength": 120}, "host": {"type": "string", "maxLength": 120}, "port": {"type": "integer", "minimum": 1, "maximum": 65535}}, ["mode"]), tool_schema({})),
    "service_status": ServerTool("service_status", "Consulta status de servico.", "read_only", False, ("Windows",), 10, tool_schema({"service_name": {"type": "string", "maxLength": 80}}, ["service_name"]), tool_schema({})),
    "event_logs": ServerTool("event_logs", "Coleta eventos recentes.", "read_only", False, ("Windows",), 10, tool_schema({"source": {"type": "string", "maxLength": 80}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}), tool_schema({})),
    "windows_update_status": ServerTool("windows_update_status", "Consulta Windows Update.", "read_only", False, ("Windows",), 10, tool_schema({}), tool_schema({})),
}


def sanitize_payload(payload: Any) -> dict[str, Any]:
    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: ("[redacted]" if key.lower() in {"password", "token", "secret", "senha"} else scrub(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, str):
            return value[:1000]
        return value

    result = scrub(payload)
    return result if isinstance(result, dict) else {"value": result}


def _has_prohibited_term(payload: Any) -> bool:
    text = json.dumps(payload, ensure_ascii=True).lower()
    return any(term in text for term in PROHIBITED_TERMS)


def validate_arguments(tool: ServerTool, arguments: dict[str, Any]) -> str | None:
    if _has_prohibited_term({"tool_name": tool.name, "arguments": arguments}):
        return "Request contains a prohibited term."
    properties = tool.input_schema.get("properties", {})
    required = set(tool.input_schema.get("required", []))
    extra = set(arguments) - set(properties)
    missing = required - set(arguments)
    if extra:
        return f"Unsupported argument(s): {', '.join(sorted(extra))}"
    if missing:
        return f"Missing required argument(s): {', '.join(sorted(missing))}"
    for key, schema in properties.items():
        if key not in arguments:
            continue
        value = arguments[key]
        if schema.get("type") == "string" and not isinstance(value, str):
            return f"{key} must be a string."
        if schema.get("type") == "integer" and not isinstance(value, int):
            return f"{key} must be an integer."
        if isinstance(value, str) and len(value) > schema.get("maxLength", len(value)):
            return f"{key} is too long."
        if "enum" in schema and value not in schema["enum"]:
            return f"{key} is not allowed."
    return None


def evaluate_tool_request(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool = SERVER_TOOL_REGISTRY.get(tool_name)
    if tool is None:
        return {"allowed": False, "requires_approval": False, "risk_level": "prohibited", "reason": "Unknown tool."}
    reason = validate_arguments(tool, arguments)
    if reason:
        return {"allowed": False, "requires_approval": False, "risk_level": tool.risk_level, "reason": reason}
    if tool.risk_level == "medium":
        return {"allowed": False, "requires_approval": True, "risk_level": tool.risk_level, "reason": "Approval required."}
    if tool.risk_level in {"high", "prohibited"}:
        return {"allowed": False, "requires_approval": False, "risk_level": tool.risk_level, "reason": "Risk level disabled."}
    return {"allowed": True, "requires_approval": tool.requires_approval, "risk_level": tool.risk_level, "reason": "Allowed by server policy."}
