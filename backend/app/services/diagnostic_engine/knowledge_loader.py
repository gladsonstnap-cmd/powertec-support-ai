import json
from pathlib import Path
from typing import Any

from app.services.diagnostic_engine.enums import IncidentCategory, RiskLevel, SeverityLevel
from app.services.diagnostic_engine.knowledge_models import (
    DiagnosticAction,
    DiagnosticQuestion,
    DiagnosticTest,
    KnowledgeCause,
    KnowledgeIncident,
    KnowledgeValidationError,
)


class KnowledgeLoader:
    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or Path(__file__).with_name("knowledge")

    def load(self) -> list[KnowledgeIncident]:
        incidents: list[KnowledgeIncident] = []
        seen_ids: set[str] = set()

        for file_path in sorted(self.base_path.glob("*.json")):
            for raw_incident in self._read_file(file_path):
                incident = self._build_incident(raw_incident, file_path)
                if incident.id in seen_ids:
                    raise KnowledgeValidationError(f"Duplicate incident id '{incident.id}' in {file_path.name}")
                seen_ids.add(incident.id)
                incidents.append(incident)

        if not incidents:
            raise KnowledgeValidationError(f"No knowledge incidents found in {self.base_path}")

        return incidents

    def _read_file(self, file_path: Path) -> list[dict[str, Any]]:
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise KnowledgeValidationError(f"Invalid JSON in {file_path.name}: {exc.msg}") from exc

        if isinstance(payload, dict):
            payload = payload.get("incidents")

        if not isinstance(payload, list):
            raise KnowledgeValidationError(f"{file_path.name} must contain an incidents list")

        if not all(isinstance(item, dict) for item in payload):
            raise KnowledgeValidationError(f"{file_path.name} contains a non-object incident")

        return payload

    def _build_incident(self, raw: dict[str, Any], file_path: Path) -> KnowledgeIncident:
        incident_id = self._required_text(raw, "id", file_path)
        try:
            incident = KnowledgeIncident(
                id=incident_id,
                title=self._required_text(raw, "title", file_path),
                description=self._required_text(raw, "description", file_path),
                category=IncidentCategory(self._required_text(raw, "category", file_path)),
                default_severity=SeverityLevel(self._required_text(raw, "default_severity", file_path)),
                symptoms=self._required_text_list(raw, "symptoms", file_path),
                possible_causes=self._build_causes(raw.get("possible_causes"), incident_id, file_path),
                questions=self._build_questions(raw.get("questions"), incident_id, file_path),
                recommended_tests=self._build_tests(raw.get("recommended_tests"), incident_id, file_path),
                recommended_actions=self._build_actions(raw.get("recommended_actions"), incident_id, file_path),
                required_information=self._required_text_list(raw, "required_information", file_path),
                escalation_conditions=self._optional_text_list(raw, "escalation_conditions", file_path),
                requires_remote_diagnostic=bool(raw.get("requires_remote_diagnostic", False)),
                requires_human=bool(raw.get("requires_human", False)),
                tags=self._optional_text_list(raw, "tags", file_path),
            )
        except ValueError as exc:
            if isinstance(exc, KnowledgeValidationError):
                raise
            raise KnowledgeValidationError(f"Invalid enum value in incident '{incident_id}' ({file_path.name})") from exc

        self._validate_incident_safety(incident, file_path)
        return incident

    def _build_causes(self, value: Any, incident_id: str, file_path: Path) -> list[KnowledgeCause]:
        items = self._required_object_list(value, "possible_causes", incident_id, file_path)
        causes = [
            KnowledgeCause(
                id=self._required_text(item, "id", file_path),
                description=self._required_text(item, "description", file_path),
                base_confidence=self._confidence(item.get("base_confidence"), item.get("id"), file_path),
                supporting_evidence=self._required_text_list(item, "supporting_evidence", file_path),
                contradicting_evidence=self._optional_text_list(item, "contradicting_evidence", file_path),
                risk_level=RiskLevel(self._required_text(item, "risk_level", file_path)),
            )
            for item in items
        ]
        self._ensure_unique([cause.id for cause in causes], "cause", incident_id, file_path)
        return causes

    def _build_questions(self, value: Any, incident_id: str, file_path: Path) -> list[DiagnosticQuestion]:
        items = self._required_object_list(value, "questions", incident_id, file_path)
        questions = [
            DiagnosticQuestion(
                id=self._required_text(item, "id", file_path),
                text=self._required_text(item, "text", file_path),
                field=self._required_text(item, "field", file_path),
                priority=int(item.get("priority", 100)),
                answer_type=self._required_text(item, "answer_type", file_path),
                options=self._optional_text_list(item, "options", file_path),
                required=bool(item.get("required", False)),
            )
            for item in items
        ]
        self._ensure_unique([question.id for question in questions], "question", incident_id, file_path)
        return questions

    def _build_tests(self, value: Any, incident_id: str, file_path: Path) -> list[DiagnosticTest]:
        items = self._required_object_list(value, "recommended_tests", incident_id, file_path)
        tests = [
            DiagnosticTest(
                id=self._required_text(item, "id", file_path),
                title=self._required_text(item, "title", file_path),
                description=self._required_text(item, "description", file_path),
                tool_name=self._required_text(item, "tool_name", file_path),
                risk_level=RiskLevel(self._required_text(item, "risk_level", file_path)),
                requires_remote_agent=bool(item.get("requires_remote_agent", False)),
                requires_approval=bool(item.get("requires_approval", False)),
                expected_results=self._required_text_list(item, "expected_results", file_path),
            )
            for item in items
        ]
        self._ensure_unique([test.id for test in tests], "test", incident_id, file_path)
        return tests

    def _build_actions(self, value: Any, incident_id: str, file_path: Path) -> list[DiagnosticAction]:
        items = self._required_object_list(value, "recommended_actions", incident_id, file_path)
        actions = [
            DiagnosticAction(
                id=self._required_text(item, "id", file_path),
                title=self._required_text(item, "title", file_path),
                description=self._required_text(item, "description", file_path),
                tool_name=self._required_text(item, "tool_name", file_path),
                risk_level=RiskLevel(self._required_text(item, "risk_level", file_path)),
                requires_approval=bool(item.get("requires_approval", False)),
                requires_human=bool(item.get("requires_human", False)),
            )
            for item in items
        ]
        self._ensure_unique([action.id for action in actions], "action", incident_id, file_path)
        return actions

    def _validate_incident_safety(self, incident: KnowledgeIncident, file_path: Path) -> None:
        for test in incident.recommended_tests:
            if test.risk_level == RiskLevel.READ_ONLY and test.requires_approval:
                raise KnowledgeValidationError(f"Read-only test '{test.id}' must not require approval ({file_path.name})")
            if test.risk_level != RiskLevel.READ_ONLY and not test.requires_approval:
                raise KnowledgeValidationError(f"Non-read-only test '{test.id}' must require approval ({file_path.name})")

        for action in incident.recommended_actions:
            if action.risk_level in {RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL} and not action.requires_approval:
                raise KnowledgeValidationError(f"Action '{action.id}' must require approval ({file_path.name})")
            if action.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL} and not action.requires_human:
                raise KnowledgeValidationError(f"High-risk action '{action.id}' must require human execution ({file_path.name})")

    def _required_text(self, raw: dict[str, Any], key: str, file_path: Path) -> str:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise KnowledgeValidationError(f"Missing required text field '{key}' in {file_path.name}")
        return value.strip()

    def _required_text_list(self, raw: dict[str, Any], key: str, file_path: Path) -> list[str]:
        values = self._optional_text_list(raw, key, file_path)
        if not values:
            raise KnowledgeValidationError(f"Missing required list field '{key}' in {file_path.name}")
        return values

    def _optional_text_list(self, raw: dict[str, Any], key: str, file_path: Path) -> list[str]:
        value = raw.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            raise KnowledgeValidationError(f"Field '{key}' must be a list of non-empty strings in {file_path.name}")
        return [item.strip() for item in value]

    def _required_object_list(self, value: Any, key: str, incident_id: str, file_path: Path) -> list[dict[str, Any]]:
        if not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value):
            raise KnowledgeValidationError(f"Incident '{incident_id}' requires a non-empty object list '{key}' ({file_path.name})")
        return value

    def _confidence(self, value: Any, item_id: Any, file_path: Path) -> float:
        if not isinstance(value, int | float) or not 0.0 <= float(value) <= 1.0:
            raise KnowledgeValidationError(f"Cause '{item_id}' has invalid confidence in {file_path.name}")
        return float(value)

    def _ensure_unique(self, values: list[str], item_type: str, incident_id: str, file_path: Path) -> None:
        if len(values) != len(set(values)):
            raise KnowledgeValidationError(f"Incident '{incident_id}' has duplicate {item_type} ids ({file_path.name})")
