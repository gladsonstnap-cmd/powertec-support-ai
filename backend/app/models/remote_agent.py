from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


def utcnow() -> datetime:
    return datetime.now(UTC)


class RemoteAgent(IdMixin, Base):
    __tablename__ = "remote_agents"
    __table_args__ = (UniqueConstraint("agent_uuid", name="uq_remote_agents_agent_uuid"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    agent_uuid: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    hostname: Mapped[str] = mapped_column(String(160), nullable=False)
    operating_system: Mapped[str] = mapped_column(String(80), nullable=False)
    os_version: Mapped[str | None] = mapped_column(String(160))
    architecture: Mapped[str | None] = mapped_column(String(80))
    agent_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="offline")
    mode: Mapped[str] = mapped_column(String(40), nullable=False, default="simulation")
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class AgentCommand(IdMixin, Base):
    __tablename__ = "agent_commands"
    __table_args__ = (UniqueConstraint("request_uuid", name="uq_agent_commands_request_uuid"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("remote_agents.id"), index=True, nullable=False)
    ai_diagnostic_session_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_diagnostic_sessions.id"))
    request_uuid: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    arguments_json: Mapped[dict] = mapped_column("arguments", JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="queued")
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False)
    requires_approval: Mapped[bool] = mapped_column(nullable=False, default=False)
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_json: Mapped[dict] = mapped_column("result", JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)


class AgentCommandResult(IdMixin, Base):
    __tablename__ = "agent_command_results"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    command_id: Mapped[UUID] = mapped_column(ForeignKey("agent_commands.id"), index=True, nullable=False)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("remote_agents.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    result_json: Mapped[dict] = mapped_column("result", JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AgentAuditEvent(IdMixin, Base):
    __tablename__ = "agent_audit_events"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("remote_agents.id"), index=True)
    command_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_commands.id"), index=True)
    request_uuid: Mapped[str | None] = mapped_column(String(80), index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(120))
    sanitized_arguments: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    policy_decision: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    approval: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict] = mapped_column("result", JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    agent_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
