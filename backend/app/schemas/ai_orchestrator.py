from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.ai_orchestrator import (
    AIApprovalStatus,
    AIAutonomyLevel,
    AIPlanStepStatus,
    AIPriority,
    AIRiskLevel,
    AISessionStatus,
)


class AIHypothesisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    code: str
    title: str
    description: str
    probability: float
    rank: int
    status: str
    evidence: dict
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    last_updated_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class AIPlanStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    sequence: int
    tool_name: str
    title: str
    description: str
    parameters: dict
    risk_level: AIRiskLevel
    requires_approval: bool
    status: AIPlanStepStatus
    attempt_count: int
    max_attempts: int
    result: dict
    selection_reason: str | None = None
    evidence_result: dict = Field(default_factory=dict)
    is_dynamic: bool = False
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AISessionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    session_id: UUID
    event_type: str
    message: str
    metadata: dict = Field(default_factory=dict, validation_alias="metadata_json")
    actor_type: str
    created_at: datetime


class AIApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    plan_step_id: UUID
    status: AIApprovalStatus
    requested_at: datetime
    decided_at: datetime | None = None
    decided_by: UUID | None = None
    decision_reason: str | None = None


class AIDiagnosticSessionCreate(BaseModel):
    ticket_id: UUID
    customer_message: str = Field(min_length=5)
    channel: str = Field(default="portal", max_length=40)
    autonomy_level: AIAutonomyLevel = AIAutonomyLevel.DIAGNOSTIC_ONLY
    simulation_scenario: str = Field(default="healthy", max_length=60)


class AIApprovalDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class AIDiagnosticSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ticket_id: UUID
    customer_message: str
    channel: str
    autonomy_level: AIAutonomyLevel
    status: AISessionStatus
    category: str | None = None
    priority: AIPriority | None = None
    confidence: float | None = None
    current_risk_level: AIRiskLevel
    resolution_summary: str | None = None
    escalation_reason: str | None = None
    failure_reason: str | None = None
    max_steps: int
    executed_steps: int
    consecutive_failures: int
    created_by: UUID
    simulation_scenario: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    hypotheses: list[AIHypothesisRead] = Field(default_factory=list)
    plan_steps: list[AIPlanStepRead] = Field(default_factory=list)
    approvals: list[AIApprovalRead] = Field(default_factory=list)
    events: list[AISessionEventRead] = Field(default_factory=list)
    last_decision: str | None = None
    decision_reason: str | None = None
    recommended_tool: str | None = None
    final_confidence: float | None = None
