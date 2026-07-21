import json
import re
from typing import Any

from agent.config import AgentConfig
from agent.models import RiskLevel, ToolDefinition
from agent.registry import build_registry

PROHIBITED_TERMS = (
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
)


class PolicyError(ValueError):
    pass


def contains_prohibited_term(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=True).lower()
    return any(term in text for term in PROHIBITED_TERMS)


def validate_tool_arguments(tool: ToolDefinition, arguments: dict[str, Any]) -> None:
    if contains_prohibited_term({"tool_name": tool.name, "arguments": arguments}):
        raise PolicyError("Request contains a prohibited term.")
    allowed = set(tool.input_schema.get("properties", {}))
    required = set(tool.input_schema.get("required", []))
    extra = set(arguments) - allowed
    missing = required - set(arguments)
    if extra:
        raise PolicyError(f"Unsupported argument(s): {', '.join(sorted(extra))}")
    if missing:
        raise PolicyError(f"Missing required argument(s): {', '.join(sorted(missing))}")
    for key, schema in tool.input_schema.get("properties", {}).items():
        if key not in arguments:
            continue
        value = arguments[key]
        if schema.get("type") == "integer":
            if not isinstance(value, int):
                raise PolicyError(f"{key} must be an integer.")
            if value < schema.get("minimum", value) or value > schema.get("maximum", value):
                raise PolicyError(f"{key} is outside the allowed range.")
        if schema.get("type") == "string":
            if not isinstance(value, str):
                raise PolicyError(f"{key} must be a string.")
            if len(value) > schema.get("maxLength", len(value)):
                raise PolicyError(f"{key} is too long.")
            if re.search(r"[;&|`$<>]", value):
                raise PolicyError(f"{key} contains unsafe characters.")
        if "enum" in schema and value not in schema["enum"]:
            raise PolicyError(f"{key} is not an allowed value.")


def is_prohibited(tool_name: str, arguments: dict[str, Any], config: AgentConfig | None = None) -> bool:
    try:
        tool = build_registry(config)[tool_name]
        validate_tool_arguments(tool, arguments)
    except (KeyError, PolicyError):
        return True
    return tool.risk_level == RiskLevel.PROHIBITED


def requires_approval(tool: ToolDefinition, config: AgentConfig) -> bool:
    if tool.risk_level == RiskLevel.MEDIUM:
        return True
    if tool.risk_level == RiskLevel.LOW:
        return not config.allow_low_risk_auto
    return tool.requires_approval


def evaluate_tool_request(tool_name: str, arguments: dict[str, Any], approved: bool = False, config: AgentConfig | None = None) -> dict[str, Any]:
    active_config = config or AgentConfig()
    registry = build_registry(active_config)
    if tool_name not in registry:
        return {"allowed": False, "requires_approval": False, "risk_level": "prohibited", "reason": "Unknown tool."}
    tool = registry[tool_name]
    try:
        validate_tool_arguments(tool, arguments)
    except PolicyError as exc:
        return {"allowed": False, "requires_approval": False, "risk_level": tool.risk_level.value, "reason": str(exc)}
    if not tool.timeout_seconds:
        return {"allowed": False, "requires_approval": False, "risk_level": tool.risk_level.value, "reason": "Tool timeout is required."}
    if tool.risk_level in {RiskLevel.HIGH, RiskLevel.PROHIBITED}:
        return {"allowed": False, "requires_approval": False, "risk_level": tool.risk_level.value, "reason": "Risk level is disabled."}
    needs_approval = requires_approval(tool, active_config)
    if needs_approval and not approved:
        return {"allowed": False, "requires_approval": True, "risk_level": tool.risk_level.value, "reason": "Approval required."}
    return {"allowed": True, "requires_approval": needs_approval, "risk_level": tool.risk_level.value, "reason": "Allowed by policy."}


def sanitize_output(payload: Any, limit_bytes: int = 32_768) -> dict[str, Any]:
    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: ("[redacted]" if key.lower() in {"password", "token", "secret", "senha"} else scrub(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, str):
            return value[:1000]
        return value

    sanitized = scrub(payload)
    encoded = json.dumps(sanitized, ensure_ascii=True)
    if len(encoded.encode("utf-8")) > limit_bytes:
        return {"truncated": True, "payload": encoded[:limit_bytes]}
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}
