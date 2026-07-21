"""remote agents

Revision ID: 0006_remote_agents
Revises: 0005_ai_intelligence
Create Date: 2026-07-19 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_remote_agents"
down_revision = "0005_ai_intelligence"
branch_labels = None
depends_on = None

JSON_EMPTY_OBJECT = sa.text("'{}'::json")


def upgrade() -> None:
    op.create_table(
        "remote_agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("agent_uuid", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("hostname", sa.String(160), nullable=False),
        sa.Column("operating_system", sa.String(80), nullable=False),
        sa.Column("os_version", sa.String(160)),
        sa.Column("architecture", sa.String(80)),
        sa.Column("agent_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="offline"),
        sa.Column("mode", sa.String(40), nullable=False, server_default="simulation"),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_uuid", name="uq_remote_agents_agent_uuid"),
    )
    op.create_index("ix_remote_agents_tenant_id", "remote_agents", ["tenant_id"])
    op.create_index("ix_remote_agents_agent_uuid", "remote_agents", ["agent_uuid"])
    op.create_index("ix_remote_agents_status", "remote_agents", ["status"])

    op.create_table(
        "agent_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("remote_agents.id"), nullable=False),
        sa.Column("ai_diagnostic_session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_diagnostic_sessions.id")),
        sa.Column("request_uuid", sa.String(80), nullable=False),
        sa.Column("tool_name", sa.String(120), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("status", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("risk_level", sa.String(40), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("result", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("error_message", sa.Text()),
        sa.UniqueConstraint("request_uuid", name="uq_agent_commands_request_uuid"),
    )
    op.create_index("ix_agent_commands_tenant_id", "agent_commands", ["tenant_id"])
    op.create_index("ix_agent_commands_agent_id", "agent_commands", ["agent_id"])
    op.create_index("ix_agent_commands_request_uuid", "agent_commands", ["request_uuid"])
    op.create_index("ix_agent_commands_status", "agent_commands", ["status"])

    op.create_table(
        "agent_command_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_commands.id"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("remote_agents.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("error_message", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_command_results_tenant_id", "agent_command_results", ["tenant_id"])
    op.create_index("ix_agent_command_results_command_id", "agent_command_results", ["command_id"])
    op.create_index("ix_agent_command_results_agent_id", "agent_command_results", ["agent_id"])

    op.create_table(
        "agent_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("remote_agents.id")),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_commands.id")),
        sa.Column("request_uuid", sa.String(80)),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("tool_name", sa.String(120)),
        sa.Column("sanitized_arguments", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("policy_decision", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("approval", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("result", sa.JSON(), nullable=False, server_default=JSON_EMPTY_OBJECT),
        sa.Column("error_message", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("agent_version", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_audit_events_tenant_id", "agent_audit_events", ["tenant_id"])
    op.create_index("ix_agent_audit_events_agent_id", "agent_audit_events", ["agent_id"])
    op.create_index("ix_agent_audit_events_command_id", "agent_audit_events", ["command_id"])
    op.create_index("ix_agent_audit_events_request_uuid", "agent_audit_events", ["request_uuid"])


def downgrade() -> None:
    op.drop_table("agent_audit_events")
    op.drop_table("agent_command_results")
    op.drop_table("agent_commands")
    op.drop_table("remote_agents")
