"""ai diagnostic orchestrator

Revision ID: 0004_ai_orchestrator
Revises: 0003_support_agent_knowledge
Create Date: 2026-07-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_ai_orchestrator"
down_revision = "0003_support_agent_knowledge"
branch_labels = None
depends_on = None

JSON_EMPTY_OBJECT = sa.text("'{}'::json")


def upgrade() -> None:
    op.create_table(
        "ai_diagnostic_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("customer_message", sa.Text(), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("autonomy_level", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("category", sa.String(80)),
        sa.Column("priority", sa.String(20)),
        sa.Column("confidence", sa.Float()),
        sa.Column("current_risk_level", sa.String(20), nullable=False),
        sa.Column("resolution_summary", sa.Text()),
        sa.Column("escalation_reason", sa.Text()),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("max_steps", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("executed_steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("simulation_scenario", sa.String(60), nullable=False, server_default="healthy"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_ai_diagnostic_sessions_tenant_id", "ai_diagnostic_sessions", ["tenant_id"])
    op.create_index("ix_ai_diagnostic_sessions_ticket_id", "ai_diagnostic_sessions", ["ticket_id"])
    op.create_index("ix_ai_diagnostic_sessions_status", "ai_diagnostic_sessions", ["status"])
    op.create_index("ix_ai_diagnostic_sessions_created_at", "ai_diagnostic_sessions", ["created_at"])

    op.create_table(
        "ai_hypotheses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("ai_diagnostic_sessions.id"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="OPEN"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_hypotheses_tenant_id", "ai_hypotheses", ["tenant_id"])
    op.create_index("ix_ai_hypotheses_session_id", "ai_hypotheses", ["session_id"])

    op.create_table(
        "ai_plan_steps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("ai_diagnostic_sessions.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(120), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("result", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_plan_steps_tenant_id", "ai_plan_steps", ["tenant_id"])
    op.create_index("ix_ai_plan_steps_session_id", "ai_plan_steps", ["session_id"])
    op.create_index("ix_ai_plan_steps_status", "ai_plan_steps", ["status"])

    op.create_table(
        "ai_session_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("ai_diagnostic_sessions.id"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("actor_type", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_session_events_tenant_id", "ai_session_events", ["tenant_id"])
    op.create_index("ix_ai_session_events_session_id", "ai_session_events", ["session_id"])
    op.create_index("ix_ai_session_events_created_at", "ai_session_events", ["created_at"])

    op.create_table(
        "ai_approvals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("ai_diagnostic_sessions.id"), nullable=False),
        sa.Column("plan_step_id", sa.Uuid(), sa.ForeignKey("ai_plan_steps.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("decision_reason", sa.Text()),
    )
    op.create_index("ix_ai_approvals_tenant_id", "ai_approvals", ["tenant_id"])
    op.create_index("ix_ai_approvals_session_id", "ai_approvals", ["session_id"])
    op.create_index("ix_ai_approvals_plan_step_id", "ai_approvals", ["plan_step_id"])
    op.create_index("ix_ai_approvals_status", "ai_approvals", ["status"])


def downgrade() -> None:
    op.drop_table("ai_approvals")
    op.drop_table("ai_session_events")
    op.drop_table("ai_plan_steps")
    op.drop_table("ai_hypotheses")
    op.drop_table("ai_diagnostic_sessions")
