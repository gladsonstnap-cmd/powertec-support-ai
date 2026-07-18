from types import SimpleNamespace

import pytest

from app.models.ai_orchestrator import AIAutonomyLevel, AIRiskLevel, AIPlanStepStatus
from app.services.ai_orchestrator.classifier import classify_incident
from app.services.ai_orchestrator.decision_engine import decide_next
from app.services.ai_orchestrator.evaluator import evaluate_tool_result
from app.services.ai_orchestrator.hypothesis_engine import normalize_probabilities, update_hypotheses_from_evidence
from app.services.ai_orchestrator.planner import build_plan, dynamic_step
from app.services.ai_orchestrator.policy import PolicyEngine
from app.services.ai_orchestrator.tool_selector import select_next_step
from app.services.ai_orchestrator.tools import execute_tool


def hypothesis(code: str, probability: float):
    return SimpleNamespace(
        code=code,
        probability=probability,
        status="ACTIVE",
        rank=1,
        supporting_evidence=[],
        contradicting_evidence=[],
        last_updated_reason=None,
    )


def step(tool_name: str, status: str = AIPlanStepStatus.PENDING.value, result: dict | None = None, sequence: int = 1, is_dynamic: bool = False):
    return SimpleNamespace(
        tool_name=tool_name,
        status=status,
        result=result or {},
        sequence=sequence,
        is_dynamic=is_dynamic,
        max_attempts=2,
        attempt_count=0,
    )


def test_classifier_specific_categories():
    assert classify_incident("SQL Server nao inicia.").category == "DATABASE"
    assert classify_incident("Impressora nao imprime cupom.").category == "PRINTING"
    assert classify_incident("Disco C esta cheio.").category == "DISK_STORAGE"
    assert classify_incident("Nao resolve o nome do servidor.").category == "DNS"


def test_probability_normalization_is_deterministic():
    hypotheses = [hypothesis("a", 0.4), hypothesis("b", 0.4), hypothesis("c", 0.2)]
    normalize_probabilities(hypotheses)

    assert sum(item.probability for item in hypotheses) == pytest.approx(1.0)


def test_ping_success_reduces_server_unreachable():
    hypotheses = [hypothesis("server_unreachable", 0.15), hypothesis("database_service_stopped", 0.4)]
    update_hypotheses_from_evidence(hypotheses, ["SERVER_REACHABLE"])

    unreachable = next(item for item in hypotheses if item.code == "server_unreachable")
    assert unreachable.status in {"WEAKENED", "REJECTED"}
    assert unreachable.contradicting_evidence


def test_dns_success_weakens_dns_failure():
    hypotheses = [hypothesis("dns_failure", 0.2), hypothesis("database_service_stopped", 0.4)]
    update_hypotheses_from_evidence(hypotheses, ["DNS_RESOLVED"])

    dns = next(item for item in hypotheses if item.code == "dns_failure")
    assert dns.status in {"WEAKENED", "REJECTED"}


def test_closed_port_increases_database_hypotheses():
    hypotheses = [hypothesis("database_service_stopped", 0.4), hypothesis("database_port_blocked", 0.25)]
    update_hypotheses_from_evidence(hypotheses, ["DB_PORT_CLOSED"])

    assert all(item.supporting_evidence for item in hypotheses)


def test_service_stopped_confirms_service_hypothesis():
    hypotheses = [hypothesis("database_service_stopped", 0.4), hypothesis("database_port_blocked", 0.25)]
    update_hypotheses_from_evidence(hypotheses, ["SERVICE_STOPPED"])

    service = next(item for item in hypotheses if item.code == "database_service_stopped")
    assert service.status == "CONFIRMED"


def test_service_running_weakens_service_stopped():
    hypotheses = [hypothesis("database_service_stopped", 0.4), hypothesis("database_port_blocked", 0.25)]
    update_hypotheses_from_evidence(hypotheses, ["SERVICE_RUNNING"])

    service = next(item for item in hypotheses if item.code == "database_service_stopped")
    assert service.status in {"WEAKENED", "REJECTED"}


def test_tool_selector_chooses_valid_and_avoids_duplicate_ping():
    hypotheses = [hypothesis("database_service_stopped", 0.6)]
    steps = [
        step("network.ping", AIPlanStepStatus.COMPLETED.value),
        step("network.ping", sequence=2),
        step("windows.service_status", sequence=3),
    ]
    selected = select_next_step(hypotheses, steps)

    assert selected.step is not None
    assert selected.step.tool_name == "windows.service_status"


def test_planner_dynamic_restart_step():
    draft = dynamic_step(5, "windows.service_restart", "sql_service_stopped", "Servico parado confirmado.")

    assert draft.is_dynamic is True
    assert draft.requires_approval is True
    assert draft.risk_level == AIRiskLevel.SAFE_ACTION


def test_planner_respects_max_steps_by_external_limit():
    classification = classify_incident("Todos os caixas perderam conexao com o servidor.")
    assert len(build_plan(classification, "sql_service_stopped")) <= 12


def test_evaluator_creates_evidence_codes():
    result = execute_tool("network.test_port", {"host": "servidor", "port": 1433, "scenario": "sql_service_stopped"})
    evidence = evaluate_tool_result("network.test_port", result)

    assert "DB_PORT_CLOSED" in evidence.evidence_codes


def test_decision_engine_continue_wait_approval_resolve_escalate():
    hypotheses = [hypothesis("database_service_stopped", 0.7)]
    assert decide_next(hypotheses, [step("network.ping")], 12, 0).decision == "CONTINUE"
    assert decide_next(hypotheses, [step("windows.service_restart", AIPlanStepStatus.WAITING_APPROVAL.value)], 12, 4).decision == "WAIT_APPROVAL"
    assert decide_next(hypotheses, [step("windows.service_restart", AIPlanStepStatus.COMPLETED.value, {"evidence_codes": ["SERVICE_RESTARTED"]}), step("windows.service_status", AIPlanStepStatus.COMPLETED.value, {"evidence_codes": ["SERVICE_RUNNING"]})], 12, 6).decision == "RESOLVE"
    assert decide_next(hypotheses, [step("network.dns_lookup", AIPlanStepStatus.COMPLETED.value, {"evidence_codes": ["DNS_FAILED"]})], 12, 2).decision == "ESCALATE"


def test_safe_action_policy_still_requires_approval():
    decision = PolicyEngine().decide("windows.service_restart", {"service_name": "MSSQLSERVER", "scenario": "sql_service_stopped"}, AIAutonomyLevel.SAFE_ACTIONS_WITH_APPROVAL, AIRiskLevel.SAFE_ACTION)

    assert decision.needs_approval is True


def test_scenarios_dns_port_printer_and_conflicting_evidence():
    assert execute_tool("network.dns_lookup", {"hostname": "servidor", "scenario": "dns_failure"})["evidence_codes"] == ["DNS_FAILED"]
    assert execute_tool("network.test_port", {"host": "servidor", "port": 1433, "scenario": "port_blocked"})["evidence_codes"] == ["DB_PORT_CLOSED"]
    assert execute_tool("printer.list", {"scenario": "printer_offline"})["evidence_codes"] == ["PRINTER_OFFLINE"]
    assert execute_tool("windows.service_status", {"service_name": "MSSQLSERVER", "scenario": "conflicting_evidence"})["evidence_codes"] == ["SERVICE_STOPPED"]
