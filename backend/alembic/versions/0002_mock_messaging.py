"""mock messaging stage 2

Revision ID: 0002_mock_messaging
Revises: 0001_stage_1_core
Create Date: 2026-07-11 21:30:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_mock_messaging"
down_revision = "0001_stage_1_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id")),
        sa.Column("name", sa.String(160)),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("is_temporary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("validation_status", sa.String(40), nullable=False, server_default="validated"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_contacts_tenant_id", "contacts", ["tenant_id"])
    op.create_table(
        "temporary_customers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("contact_name", sa.String(160)),
        sa.Column("company_name", sa.String(160)),
        sa.Column("city", sa.String(100)),
        sa.Column("system_name", sa.String(120)),
        sa.Column("validation_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_temporary_customers_tenant_id", "temporary_customers", ["tenant_id"])
    op.create_table(
        "protocol_counters",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("next_value", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "year", name="uq_protocol_counter_tenant_year"),
    )
    op.create_index("ix_protocol_counters_tenant_id", "protocol_counters", ["tenant_id"])
    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("contacts.id")),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id")),
        sa.Column("establishment_id", sa.Uuid(), sa.ForeignKey("establishments.id")),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.id")),
        sa.Column("device_name", sa.String(80)),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id")),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("current_state", sa.String(60), nullable=False, server_default="new_contact"),
        sa.Column("collected_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("preliminary_priority", sa.String(2)),
        sa.Column("priority_rules", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("protocol", sa.String(30)),
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_conversation_sessions_tenant_id", "conversation_sessions", ["tenant_id"])
    op.create_table(
        "messaging_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("external_message_id", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("sender", sa.String(80), nullable=False),
        sa.Column("recipient", sa.String(80), nullable=False),
        sa.Column("message_type", sa.String(40), nullable=False),
        sa.Column("text_content", sa.Text()),
        sa.Column("media_id", sa.String(120)),
        sa.Column("mime_type", sa.String(120)),
        sa.Column("filename", sa.String(180)),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.String(40), nullable=False, server_default="received"),
        sa.Column("processing_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id")),
        sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("contacts.id")),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id")),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("conversation_sessions.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "provider", "external_message_id", name="uq_message_provider_external"),
    )
    op.create_index("ix_messaging_messages_tenant_id", "messaging_messages", ["tenant_id"])
    op.create_table(
        "conversation_state_transitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("conversation_sessions.id"), nullable=False),
        sa.Column("from_state", sa.String(60)),
        sa.Column("to_state", sa.String(60), nullable=False),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messaging_messages.id")),
        sa.Column("reason", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_conversation_state_transitions_tenant_id", "conversation_state_transitions", ["tenant_id"])
    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messaging_messages.id"), nullable=False),
        sa.Column("media_id", sa.String(120), nullable=False),
        sa.Column("safe_filename", sa.String(180), nullable=False),
        sa.Column("original_filename", sa.String(180)),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="accepted"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_message_attachments_tenant_id", "message_attachments", ["tenant_id"])
    op.create_table(
        "messaging_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_messaging_events_tenant_id", "messaging_events", ["tenant_id"])
    op.create_table(
        "ticket_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("messaging_message_id", sa.Uuid(), sa.ForeignKey("messaging_messages.id")),
        sa.Column("internal_note", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_messages_tenant_id", "ticket_messages", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("ticket_messages")
    op.drop_table("messaging_events")
    op.drop_table("message_attachments")
    op.drop_table("conversation_state_transitions")
    op.drop_table("messaging_messages")
    op.drop_table("conversation_sessions")
    op.drop_table("protocol_counters")
    op.drop_table("temporary_customers")
    op.drop_table("contacts")
