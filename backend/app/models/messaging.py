from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


class ConversationState(StrEnum):
    NEW_CONTACT = "new_contact"
    IDENTIFYING_CUSTOMER = "identifying_customer"
    CONFIRMING_CUSTOMER = "confirming_customer"
    REQUESTING_CONTACT_NAME = "requesting_contact_name"
    REQUESTING_COMPANY = "requesting_company"
    REQUESTING_CITY = "requesting_city"
    REQUESTING_SYSTEM = "requesting_system"
    SELECTING_ESTABLISHMENT = "selecting_establishment"
    SELECTING_DEVICE = "selecting_device"
    COLLECTING_PROBLEM = "collecting_problem"
    REQUESTING_EVIDENCE = "requesting_evidence"
    CREATING_TICKET = "creating_ticket"
    TICKET_CREATED = "ticket_created"
    WAITING_CUSTOMER = "waiting_customer"
    WAITING_ATTENDANT = "waiting_attendant"
    WAITING_EQUIPMENT = "waiting_equipment"
    WAITING_PROBLEM = "waiting_problem"
    WAITING_DATE = "waiting_date"
    WAITING_SYMPTOMS = "waiting_symptoms"
    WAITING_CONFIRMATION = "waiting_confirmation"
    READY_FOR_ATTENDANT = "ready_for_attendant"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Contact(IdMixin, Base):
    __tablename__ = "contacts"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"))
    name: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    is_temporary: Mapped[bool] = mapped_column(default=False, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(40), default="validated", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TemporaryCustomer(IdMixin, Base):
    __tablename__ = "temporary_customers"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    contact_id: Mapped[UUID] = mapped_column(ForeignKey("contacts.id"), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(160))
    company_name: Mapped[str | None] = mapped_column(String(160))
    city: Mapped[str | None] = mapped_column(String(100))
    system_name: Mapped[str | None] = mapped_column(String(120))
    validation_status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationSession(IdMixin, Base):
    __tablename__ = "conversation_sessions"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id"))
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"))
    establishment_id: Mapped[UUID | None] = mapped_column(ForeignKey("establishments.id"))
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"))
    device_name: Mapped[str | None] = mapped_column(String(80))
    ticket_id: Mapped[UUID | None] = mapped_column(ForeignKey("tickets.id"))
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    current_state: Mapped[str] = mapped_column(String(60), default=ConversationState.NEW_CONTACT.value, nullable=False)
    collected_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    preliminary_priority: Mapped[str | None] = mapped_column(String(2))
    priority_rules: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    protocol: Mapped[str | None] = mapped_column(String(30))
    unread_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationStateTransition(IdMixin, Base):
    __tablename__ = "conversation_state_transitions"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("conversation_sessions.id"), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(60))
    to_state: Mapped[str] = mapped_column(String(60), nullable=False)
    message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messaging_messages.id"))
    reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MessagingMessage(IdMixin, Base):
    __tablename__ = "messaging_messages"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "external_message_id", name="uq_message_provider_external"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    external_message_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    sender: Mapped[str] = mapped_column(String(80), nullable=False)
    recipient: Mapped[str] = mapped_column(String(80), nullable=False)
    message_type: Mapped[str] = mapped_column(String(40), nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text)
    media_id: Mapped[str | None] = mapped_column(String(120))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    filename: Mapped[str | None] = mapped_column(String(180))
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="received", nullable=False)
    processing_status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"))
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id"))
    ticket_id: Mapped[UUID | None] = mapped_column(ForeignKey("tickets.id"))
    session_id: Mapped[UUID | None] = mapped_column(ForeignKey("conversation_sessions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageAttachment(IdMixin, Base):
    __tablename__ = "message_attachments"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messaging_messages.id"), nullable=False)
    media_id: Mapped[str] = mapped_column(String(120), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(180), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(180))
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="accepted", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MessagingEvent(IdMixin, Base):
    __tablename__ = "messaging_events"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TicketMessage(IdMixin, Base):
    __tablename__ = "ticket_messages"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    ticket_id: Mapped[UUID] = mapped_column(ForeignKey("tickets.id"), nullable=False)
    messaging_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messaging_messages.id"))
    internal_note: Mapped[bool] = mapped_column(default=False, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProtocolCounter(IdMixin, Base):
    __tablename__ = "protocol_counters"
    __table_args__ = (UniqueConstraint("tenant_id", "year", name="uq_protocol_counter_tenant_year"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    next_value: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
