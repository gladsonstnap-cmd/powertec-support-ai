from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


class AISessionStatus(StrEnum):
    RECEIVED = "RECEIVED"
    CLASSIFYING = "CLASSIFYING"
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_TOOL = "WAITING_TOOL"
    ANALYZING_RESULT = "ANALYZING_RESULT"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AIPlanStepStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class AIRiskLevel(StrEnum):
    READ_ONLY = "READ_ONLY"
    SAFE_ACTION = "SAFE_ACTION"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class AIAutonomyLevel(StrEnum):
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
    SAFE_ACTIONS_WITH_APPROVAL = "SAFE_ACTIONS_WITH_APPROVAL"
    SAFE_ACTIONS_AUTOMATIC = "SAFE_ACTIONS_AUTOMATIC"


class AIPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AIApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


def utcnow() -> datetime:
    return datetime.now(UTC)


class AIDiagnosticSession(IdMixin, Base):
    __tablename__ = "ai_diagnostic_sessions"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    ticket_id: Mapped[UUID] = mapped_column(ForeignKey("tickets.id"), index=True, nullable=False)
    customer_message: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    autonomy_level: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default=AISessionStatus.RECEIVED.value)
    category: Mapped[str | None] = mapped_column(String(80))
    priority: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float)
    current_risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default=AIRiskLevel.READ_ONLY.value)
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    escalation_reason: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    max_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    executed_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    simulation_scenario: Mapped[str] = mapped_column(String(60), nullable=False, default="healthy")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_decision: Mapped[str | None] = mapped_column(String(40))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    recommended_tool: Mapped[str | None] = mapped_column(String(120))
    final_confidence: Mapped[float | None] = mapped_column(Float)


class AIHypothesis(IdMixin, Base):
    __tablename__ = "ai_hypotheses"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("ai_diagnostic_sessions.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="OPEN")
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    supporting_evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    contradicting_evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    last_updated_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class AIPlanStep(IdMixin, Base):
    __tablename__ = "ai_plan_steps"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("ai_diagnostic_sessions.id"), index=True, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    requires_approval: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default=AIPlanStepStatus.PENDING.value)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    selection_reason: Mapped[str | None] = mapped_column(Text)
    evidence_result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_dynamic: Mapped[bool] = mapped_column(nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class AISessionEvent(IdMixin, Base):
    __tablename__ = "ai_session_events"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("ai_diagnostic_sessions.id"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)


class AIApproval(IdMixin, Base):
    __tablename__ = "ai_approvals"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("ai_diagnostic_sessions.id"), index=True, nullable=False)
    plan_step_id: Mapped[UUID] = mapped_column(ForeignKey("ai_plan_steps.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default=AIApprovalStatus.PENDING.value)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    decision_reason: Mapped[str | None] = mapped_column(Text)
