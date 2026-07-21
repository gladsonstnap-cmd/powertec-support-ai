from uuid import uuid4

from app.services.remote_agent_policy import SERVER_TOOL_REGISTRY, evaluate_tool_request

ORCHESTRATOR_TOOL_MAP = {
    "system.inventory": "system_info",
    "disk.health": "disk_health",
    "network.ping": "network_test",
    "network.dns_lookup": "network_test",
    "network.test_port": "network_test",
    "windows.service_status": "service_status",
    "windows.event_logs": "event_logs",
}


def build_agent_command_proposal(orchestrator_tool_name: str, arguments: dict, ai_diagnostic_session_id: str | None = None) -> dict:
    tool_name = ORCHESTRATOR_TOOL_MAP.get(orchestrator_tool_name)
    if tool_name is None or tool_name not in SERVER_TOOL_REGISTRY:
        return {"status": "blocked", "reason": "No allowlisted remote-agent tool maps to this orchestrator recommendation."}
    decision = evaluate_tool_request(tool_name, arguments)
    return {
        "status": "queued" if decision["allowed"] else ("pending_approval" if decision["requires_approval"] else "blocked"),
        "request_uuid": str(uuid4()),
        "tool_name": tool_name,
        "arguments_json": arguments,
        "policy_decision": decision,
        "ai_diagnostic_session_id": ai_diagnostic_session_id,
    }
