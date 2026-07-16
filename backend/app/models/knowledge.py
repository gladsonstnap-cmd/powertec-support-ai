from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


class KnowledgeStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    INACTIVE = "inactive"


class KnowledgeDocument(IdMixin, Base):
    __tablename__ = "knowledge_documents"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(80))
    product: Mapped[str | None] = mapped_column(String(120), index=True)
    version: Mapped[str | None] = mapped_column(String(80), index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(120))
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=KnowledgeStatus.DRAFT.value, index=True, nullable=False)
    author_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    approver_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("tenant_id", "sha256", name="uq_knowledge_document_tenant_hash"),)


class KnowledgeDocumentVersion(IdMixin, Base):
    __tablename__ = "knowledge_document_versions"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("document_id", "version_number", name="uq_knowledge_version_document_number"),)


class KnowledgeChunk(IdMixin, Base):
    __tablename__ = "knowledge_chunks"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id"), index=True, nullable=False)
    version_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_document_versions.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    embedding: Mapped[list[float]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeTag(IdMixin, Base):
    __tablename__ = "knowledge_tags"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=False)
    tag: Mapped[str] = mapped_column(String(80), nullable=False)


class KnowledgeProduct(IdMixin, Base):
    __tablename__ = "knowledge_products"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=False)
    product: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str | None] = mapped_column(String(80))


class KnowledgeApproval(IdMixin, Base):
    __tablename__ = "knowledge_approvals"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    reviewer_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeSearchLog(IdMixin, Base):
    __tablename__ = "knowledge_search_logs"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    product: Mapped[str | None] = mapped_column(String(120))
    version: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str | None] = mapped_column(String(80))
    results_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TicketAnalysis(IdMixin, Base):
    __tablename__ = "ticket_analyses"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    ticket_id: Mapped[UUID] = mapped_column(ForeignKey("tickets.id"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(80))
    subcategory: Mapped[str | None] = mapped_column(String(80))
    product: Mapped[str | None] = mapped_column(String(120))
    module: Mapped[str | None] = mapped_column(String(80))
    version: Mapped[str | None] = mapped_column(String(80))
    device: Mapped[str | None] = mapped_column(String(80))
    operating_system: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    impact: Mapped[str | None] = mapped_column(Text)
    affected_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    store_stopped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fiscal_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    data_loss_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[str] = mapped_column(String(2), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_information: Mapped[list[str]] = mapped_column(JSON, default=list)
    suggested_questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    possible_causes: Mapped[list[str]] = mapped_column(JSON, default=list)
    recommended_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    knowledge_sources: Mapped[list[dict]] = mapped_column(JSON, default=list)
    triggered_rules: Mapped[list[str]] = mapped_column(JSON, default=list)
    requires_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_authorization: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    safety_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    accepted_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    technician_feedback: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SupportAuditLog(IdMixin, Base):
    __tablename__ = "support_audit_logs"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    ticket_id: Mapped[UUID | None] = mapped_column(ForeignKey("tickets.id"))
    analysis_id: Mapped[UUID | None] = mapped_column(ForeignKey("ticket_analyses.id"))
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    agent_version: Mapped[str | None] = mapped_column(String(40))
    provider: Mapped[str | None] = mapped_column(String(40))
    triggered_rules: Mapped[list[str]] = mapped_column(JSON, default=list)
    document_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    customer_response: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
