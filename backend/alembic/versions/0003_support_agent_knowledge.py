"""support agent and knowledge base

Revision ID: 0003_support_agent_knowledge
Revises: 0002_mock_messaging
Create Date: 2026-07-13 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_support_agent_knowledge"
down_revision = "0002_mock_messaging"
branch_labels = None
depends_on = None


JSON_EMPTY_OBJECT = sa.text("'{}'::json")
JSON_EMPTY_ARRAY = sa.text("'[]'::json")


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("category", sa.String(80)),
        sa.Column("product", sa.String(120)),
        sa.Column("version", sa.String(80)),
        sa.Column("manufacturer", sa.String(120)),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("author_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("approver_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "sha256", name="uq_knowledge_document_tenant_hash"),
    )
    op.create_index("ix_knowledge_documents_tenant_id", "knowledge_documents", ["tenant_id"])
    op.create_index("ix_knowledge_documents_product", "knowledge_documents", ["product"])
    op.create_index("ix_knowledge_documents_version", "knowledge_documents", ["version"])
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])

    op.create_table(
        "knowledge_document_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "version_number", name="uq_knowledge_version_document_number"),
    )
    op.create_index("ix_knowledge_document_versions_tenant_id", "knowledge_document_versions", ["tenant_id"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id"), nullable=False),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("knowledge_document_versions.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY),
        sa.Column("embedding", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_chunks_tenant_id", "knowledge_chunks", ["tenant_id"])
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])

    op.create_table(
        "knowledge_tags",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id"), nullable=False),
        sa.Column("tag", sa.String(80), nullable=False),
    )
    op.create_index("ix_knowledge_tags_tenant_id", "knowledge_tags", ["tenant_id"])

    op.create_table(
        "knowledge_products",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id"), nullable=False),
        sa.Column("product", sa.String(120), nullable=False),
        sa.Column("version", sa.String(80)),
    )
    op.create_index("ix_knowledge_products_tenant_id", "knowledge_products", ["tenant_id"])

    op.create_table(
        "knowledge_approvals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_approvals_tenant_id", "knowledge_approvals", ["tenant_id"])

    op.create_table(
        "knowledge_search_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("product", sa.String(120)),
        sa.Column("version", sa.String(80)),
        sa.Column("category", sa.String(80)),
        sa.Column("results_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_search_logs_tenant_id", "knowledge_search_logs", ["tenant_id"])

    op.create_table(
        "ticket_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("agent_version", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("category", sa.String(80)),
        sa.Column("subcategory", sa.String(80)),
        sa.Column("product", sa.String(120)),
        sa.Column("module", sa.String(80)),
        sa.Column("version", sa.String(80)),
        sa.Column("device", sa.String(80)),
        sa.Column("operating_system", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("impact", sa.Text()),
        sa.Column("affected_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("store_stopped", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fiscal_risk", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("data_loss_risk", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("priority", sa.String(2), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_information", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY),
        sa.Column("suggested_questions", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY),
        sa.Column("possible_causes", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY),
        sa.Column("recommended_actions", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY),
        sa.Column("knowledge_sources", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY),
        sa.Column("triggered_rules", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY),
        sa.Column("requires_human", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("requires_authorization", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("safety_notes", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY),
        sa.Column("accepted_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("technician_feedback", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_analyses_tenant_id", "ticket_analyses", ["tenant_id"])
    op.create_index("ix_ticket_analyses_ticket_id", "ticket_analyses", ["ticket_id"])

    op.create_table(
        "support_audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id")),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("ticket_analyses.id")),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("agent_version", sa.String(40)),
        sa.Column("provider", sa.String(40)),
        sa.Column("triggered_rules", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY),
        sa.Column("document_ids", sa.JSON(), nullable=False, server_default=JSON_EMPTY_ARRAY),
        sa.Column("result", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("customer_response", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_support_audit_logs_tenant_id", "support_audit_logs", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("support_audit_logs")
    op.drop_table("ticket_analyses")
    op.drop_table("knowledge_search_logs")
    op.drop_table("knowledge_approvals")
    op.drop_table("knowledge_products")
    op.drop_table("knowledge_tags")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_document_versions")
    op.drop_table("knowledge_documents")
