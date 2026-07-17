import pytest

from app.models.ai_orchestrator import AIAutonomyLevel, AIRiskLevel, AISessionStatus
from app.services.ai_orchestrator.classifier import classify_incident
from app.services.ai_orchestrator.evaluator import has_resolution_evidence, should_escalate_after_failures
from app.services.ai_orchestrator.planner import build_plan
from app.services.ai_orchestrator.policy import PolicyEngine
from app.services.ai_orchestrator.state_machine import InvalidStateTransition, assert_transition
from app.services.ai_orchestrator.tools import ToolValidationError, execute_tool, get_tool, validate_parameters


def test_classifier_returns_structured_network_incident():
    result = classify_incident("Todos os caixas perderam conexao com o servidor.")

    assert result.category == "NETWORK_SERVER"
    assert result.priority.value == "HIGH"
    assert result.confidence == pytest.approx(0.91)
    assert [hypothesis.code for hypothesis in result.hypotheses] == ["database_service_stopped", "database_port_blocked", "dns_failure"]


def test_planner_generates_expected_sql_service_plan():
    classification = classify_incident("Todos os caixas perderam conexao com o servidor.")
    plan = build_plan(classification, "sql_service_stopped")

    assert [step.tool_name for step in plan] == [
        "network.ping",
        "network.dns_lookup",
        "network.test_port",
        "windows.service_status",
        "windows.service_restart",
        "windows.service_status",
    ]
    assert plan[4].risk_level == AIRiskLevel.SAFE_ACTION
    assert plan[4].requires_approval is True


def test_read_only_tool_executes_without_real_system_access():
    result = execute_tool("network.ping", {"host": "servidor", "scenario": "sql_service_stopped"})

    assert result["simulation"] is True
    assert result["success"] is True
    assert result["evidence"]["reachable"] is True


def test_unknown_tool_is_rejected():
    with pytest.raises(ToolValidationError, match="Unknown tool"):
        get_tool("os.run_command")


def test_dangerous_parameters_are_rejected():
    tool = get_tool("network.ping")

    with pytest.raises(ToolValidationError, match="Dangerous parameter"):
        validate_parameters(tool, {"host": "servidor", "command": "format c:"})


def test_unsupported_parameters_are_rejected():
    tool = get_tool("network.test_port")

    with pytest.raises(ToolValidationError, match="Unsupported parameters"):
        validate_parameters(tool, {"host": "servidor", "port": 1433, "path": "C:\\temp"})


def test_safe_action_policy_requires_approval():
    decision = PolicyEngine().decide(
        "windows.service_restart",
        {"service_name": "MSSQLSERVER", "scenario": "sql_service_stopped"},
        AIAutonomyLevel.SAFE_ACTIONS_WITH_APPROVAL,
        AIRiskLevel.SAFE_ACTION,
    )

    assert decision.allowed is False
    assert decision.needs_approval is True


def test_safe_action_policy_blocks_diagnostic_only():
    decision = PolicyEngine().decide(
        "windows.service_restart",
        {"service_name": "MSSQLSERVER", "scenario": "sql_service_stopped"},
        AIAutonomyLevel.DIAGNOSTIC_ONLY,
        AIRiskLevel.SAFE_ACTION,
    )

    assert decision.allowed is False
    assert decision.needs_approval is False


def test_restricted_and_blocked_actions_are_never_allowed():
    restricted = PolicyEngine().decide("network.ping", {"host": "servidor"}, AIAutonomyLevel.SAFE_ACTIONS_AUTOMATIC, AIRiskLevel.RESTRICTED)
    blocked = PolicyEngine().decide("network.ping", {"host": "servidor"}, AIAutonomyLevel.SAFE_ACTIONS_AUTOMATIC, AIRiskLevel.BLOCKED)

    assert restricted.allowed is False
    assert blocked.allowed is False


def test_state_machine_rejects_invalid_transition():
    with pytest.raises(InvalidStateTransition):
        assert_transition(AISessionStatus.RESOLVED, AISessionStatus.RUNNING)


def test_failure_threshold_escalates_after_three_failures():
    assert should_escalate_after_failures(2, 3) is False
    assert should_escalate_after_failures(3, 3) is True


def test_resolution_requires_evidence():
    assert has_resolution_evidence([]) is False
    assert has_resolution_evidence([{"success": True, "evidence": {"status": "running"}}]) is True
    assert has_resolution_evidence([{"success": True, "evidence": {}}]) is False


def test_sql_service_stopped_tool_sequence_reaches_simulated_resolution_after_approval():
    ping = execute_tool("network.ping", {"host": "servidor", "scenario": "sql_service_stopped"})
    dns = execute_tool("network.dns_lookup", {"hostname": "servidor", "scenario": "sql_service_stopped"})
    port = execute_tool("network.test_port", {"host": "servidor", "port": 1433, "scenario": "sql_service_stopped"})
    status = execute_tool("windows.service_status", {"service_name": "MSSQLSERVER", "scenario": "sql_service_stopped"})
    restart_decision = PolicyEngine().decide(
        "windows.service_restart",
        {"service_name": "MSSQLSERVER", "scenario": "sql_service_stopped"},
        AIAutonomyLevel.SAFE_ACTIONS_WITH_APPROVAL,
        AIRiskLevel.SAFE_ACTION,
    )
    restart = execute_tool("windows.service_restart", {"service_name": "MSSQLSERVER", "scenario": "sql_service_stopped"})
    confirmation = execute_tool("windows.service_status", {"service_name": "MSSQLSERVER", "scenario": "healthy"})

    assert ping["success"] is True
    assert dns["success"] is True
    assert port["success"] is True
    assert port["evidence"]["open"] is False
    assert status["evidence"]["status"] == "stopped"
    assert restart_decision.needs_approval is True
    assert restart["evidence"]["restarted"] is True
    assert confirmation["evidence"]["status"] == "running"
    assert has_resolution_evidence([restart, confirmation]) is True
