from agent.config import AgentConfig
from agent.models import RiskLevel, ToolDefinition
from agent.policy import evaluate_tool_request, requires_approval, sanitize_output, validate_tool_arguments


def test_read_only_tool_is_allowed():
    decision = evaluate_tool_request("system_info", {})

    assert decision["allowed"] is True
    assert decision["risk_level"] == "read_only"


def test_unknown_tool_is_blocked():
    decision = evaluate_tool_request("os_run", {})

    assert decision["allowed"] is False
    assert decision["reason"] == "Unknown tool."


def test_dangerous_terms_are_blocked():
    decision = evaluate_tool_request("network_test", {"mode": "dns", "hostname": "powershell.exe"})

    assert decision["allowed"] is False
    assert "prohibited" in decision["reason"].lower()


def test_arguments_outside_schema_are_blocked():
    decision = evaluate_tool_request("service_status", {"service_name": "Spooler", "command": "whoami"})

    assert decision["allowed"] is False


def test_medium_requires_approval():
    tool = ToolDefinition("sample", "sample", RiskLevel.MEDIUM, False, ("Windows",), 5, {"properties": {}, "required": []}, {}, lambda *_: {})

    assert requires_approval(tool, AgentConfig()) is True


def test_sanitize_output_redacts_secrets_and_limits_size():
    sanitized = sanitize_output({"token": "abc", "message": "x" * 50}, limit_bytes=20)

    assert sanitized["truncated"] is True
