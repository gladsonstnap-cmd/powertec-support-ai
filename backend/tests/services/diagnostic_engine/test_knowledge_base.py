import json
from pathlib import Path

import pytest

from app.services.diagnostic_engine.enums import IncidentCategory, RiskLevel, SeverityLevel
from app.services.diagnostic_engine.knowledge_base import KnowledgeBase
from app.services.diagnostic_engine.knowledge_loader import KnowledgeLoader
from app.services.diagnostic_engine.knowledge_models import KnowledgeValidationError


def _minimal_incident(incident_id: str = "sample_incident") -> dict:
    return {
        "id": incident_id,
        "title": "Sample incident",
        "description": "Sample deterministic diagnostic data.",
        "category": IncidentCategory.DATABASE.value,
        "default_severity": SeverityLevel.HIGH.value,
        "symptoms": ["banco nao conecta"],
        "possible_causes": [
            {
                "id": f"{incident_id}_cause",
                "description": "Servico indisponivel",
                "base_confidence": 0.7,
                "supporting_evidence": ["erro de conexao"],
                "contradicting_evidence": ["servico online"],
                "risk_level": RiskLevel.READ_ONLY.value,
            }
        ],
        "questions": [
            {
                "id": f"{incident_id}_question",
                "text": "Quando comecou?",
                "field": "started_at",
                "priority": 10,
                "answer_type": "text",
                "options": [],
                "required": True,
            }
        ],
        "recommended_tests": [
            {
                "id": f"{incident_id}_test",
                "title": "Ler contexto",
                "description": "Consulta somente leitura.",
                "tool_name": "read_context",
                "risk_level": RiskLevel.READ_ONLY.value,
                "requires_remote_agent": True,
                "requires_approval": False,
                "expected_results": ["contexto coletado"],
            }
        ],
        "recommended_actions": [
            {
                "id": f"{incident_id}_action",
                "title": "Orientar triagem",
                "description": "Sem alterar dados.",
                "tool_name": "support_triage_guidance",
                "risk_level": RiskLevel.LOW.value,
                "requires_approval": False,
                "requires_human": False,
            }
        ],
        "required_information": ["terminal", "horario"],
        "escalation_conditions": ["impacto geral"],
        "requires_remote_diagnostic": True,
        "requires_human": False,
        "tags": ["banco"],
    }


def _write_incidents(path: Path, incidents: list[dict]) -> None:
    path.write_text(json.dumps({"incidents": incidents}), encoding="utf-8")


def test_loader_loads_default_knowledge_base_with_minimum_content():
    incidents = KnowledgeLoader().load()

    assert len(incidents) >= 20
    assert len({incident.id for incident in incidents}) == len(incidents)
    assert {incident.category for incident in incidents} >= {
        IncidentCategory.DATABASE,
        IncidentCategory.PDV_STARTUP,
        IncidentCategory.FISCAL,
        IncidentCategory.PRINTER,
        IncidentCategory.TEF,
    }
    assert all(incident.symptoms for incident in incidents)
    assert all(incident.possible_causes for incident in incidents)
    assert all(incident.questions for incident in incidents)
    assert all(incident.recommended_tests for incident in incidents)
    assert all(incident.recommended_actions for incident in incidents)


def test_loaded_incidents_have_valid_confidence_and_enum_values():
    incidents = KnowledgeLoader().load()

    for incident in incidents:
        assert isinstance(incident.category, IncidentCategory)
        assert isinstance(incident.default_severity, SeverityLevel)
        for cause in incident.possible_causes:
            assert 0.0 <= cause.base_confidence <= 1.0
            assert isinstance(cause.risk_level, RiskLevel)


def test_diagnostic_read_only_tests_do_not_require_approval():
    incidents = KnowledgeLoader().load()

    for incident in incidents:
        for test in incident.recommended_tests:
            assert test.risk_level == RiskLevel.READ_ONLY
            assert test.requires_approval is False


def test_high_risk_actions_require_approval_and_human_execution():
    incidents = KnowledgeLoader().load()

    for incident in incidents:
        for action in incident.recommended_actions:
            if action.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
                assert action.requires_approval is True
                assert action.requires_human is True


def test_critical_database_incidents_require_human_attention():
    kb = KnowledgeBase.load_default()

    critical_database = [
        incident
        for incident in kb.find_by_category(IncidentCategory.DATABASE)
        if incident.default_severity == SeverityLevel.CRITICAL
    ]

    assert critical_database
    assert all(incident.requires_human for incident in critical_database)
    assert kb.get_by_id("database_possible_corruption").requires_human is True


def test_knowledge_base_list_get_and_category_lookup_are_deterministic():
    kb = KnowledgeBase.load_default()

    incidents = kb.list_all()

    assert incidents == sorted(incidents, key=lambda incident: incident.id)
    assert kb.get_by_id("pdv_application_not_starting").category == IncidentCategory.PDV_STARTUP
    assert kb.get_by_id("does_not_exist") is None
    assert all(incident.category == IncidentCategory.PRINTER for incident in kb.find_by_category(IncidentCategory.PRINTER))


def test_search_matches_accents_symptoms_tags_and_causes():
    kb = KnowledgeBase.load_default()

    results = kb.search("impressora nao imprime")

    assert results
    assert results[0].incident.id in {"receipt_printer_not_printing", "windows_spooler_stopped"}
    assert "imprime" in results[0].matched_terms or "impressora" in results[0].matched_terms
    assert 0.0 < results[0].score <= 1.0


def test_search_filters_by_category_and_limit():
    kb = KnowledgeBase.load_default()

    results = kb.search("banco nao conecta", category=IncidentCategory.DATABASE, limit=2)

    assert 1 <= len(results) <= 2
    assert all(result.incident.category == IncidentCategory.DATABASE for result in results)


def test_search_returns_empty_for_blank_unknown_or_zero_limit():
    kb = KnowledgeBase.load_default()

    assert kb.search("") == []
    assert kb.search("zzzz termo inexistente") == []
    assert kb.search("banco", limit=0) == []


def test_loader_rejects_duplicate_incident_ids(tmp_path: Path):
    incident = _minimal_incident("duplicated_incident")
    _write_incidents(tmp_path / "duplicated.json", [incident, incident])

    with pytest.raises(KnowledgeValidationError, match="Duplicate incident id"):
        KnowledgeLoader(tmp_path).load()


def test_loader_rejects_invalid_json(tmp_path: Path):
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")

    with pytest.raises(KnowledgeValidationError, match="Invalid JSON"):
        KnowledgeLoader(tmp_path).load()


def test_loader_rejects_missing_required_fields(tmp_path: Path):
    incident = _minimal_incident()
    del incident["symptoms"]
    _write_incidents(tmp_path / "missing.json", [incident])

    with pytest.raises(KnowledgeValidationError, match="symptoms"):
        KnowledgeLoader(tmp_path).load()


def test_loader_rejects_invalid_confidence(tmp_path: Path):
    incident = _minimal_incident()
    incident["possible_causes"][0]["base_confidence"] = 1.4
    _write_incidents(tmp_path / "invalid_confidence.json", [incident])

    with pytest.raises(KnowledgeValidationError, match="confidence"):
        KnowledgeLoader(tmp_path).load()


def test_loader_rejects_duplicate_nested_ids(tmp_path: Path):
    incident = _minimal_incident()
    incident["questions"].append(dict(incident["questions"][0]))
    _write_incidents(tmp_path / "duplicate_nested.json", [incident])

    with pytest.raises(KnowledgeValidationError, match="duplicate question ids"):
        KnowledgeLoader(tmp_path).load()


def test_loader_rejects_read_only_tests_that_require_approval(tmp_path: Path):
    incident = _minimal_incident()
    incident["recommended_tests"][0]["requires_approval"] = True
    _write_incidents(tmp_path / "unsafe_test.json", [incident])

    with pytest.raises(KnowledgeValidationError, match="Read-only test"):
        KnowledgeLoader(tmp_path).load()


def test_loader_rejects_high_risk_action_without_human_execution(tmp_path: Path):
    incident = _minimal_incident()
    incident["recommended_actions"][0]["risk_level"] = RiskLevel.HIGH.value
    incident["recommended_actions"][0]["requires_approval"] = True
    incident["recommended_actions"][0]["requires_human"] = False
    _write_incidents(tmp_path / "unsafe_action.json", [incident])

    with pytest.raises(KnowledgeValidationError, match="High-risk action"):
        KnowledgeLoader(tmp_path).load()


def test_knowledge_modules_do_not_depend_on_whatsapp_or_network_clients():
    import app.services.diagnostic_engine.knowledge_base as knowledge_base
    import app.services.diagnostic_engine.knowledge_loader as knowledge_loader

    combined = f"{knowledge_base.__dict__}{knowledge_loader.__dict__}".lower()

    assert "whatsapp" not in combined
    assert "httpx" not in combined
    assert "requests" not in combined
