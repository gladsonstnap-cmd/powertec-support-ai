from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models.ticket import TicketPriority, TicketStatus
from app.schemas.common import OrmModel, TenantScopedCreate


class TicketCreate(TenantScopedCreate):
    customer_id: UUID
    establishment_id: UUID | None = None
    product_id: UUID | None = None
    module: str | None = Field(default=None, max_length=80)
    priority: TicketPriority = TicketPriority.P4
    description: str = Field(min_length=5)


class TicketRead(TicketCreate, OrmModel):
    id: UUID
    protocol: str
    status: TicketStatus
    ai_summary: str | None = None
    opened_at: datetime
    closed_at: datetime | None = None


class TicketSummaryRead(OrmModel):
    id: UUID
    protocol: str
    customer_id: UUID | None = None
    customer_name: str | None = None
    contact_name: str | None = None
    company_name: str | None = None
    phone: str | None = None
    product_id: UUID | None = None
    product_name: str | None = None
    analysis_product: str | None = None
    system_name: str | None = None
    module: str | None = None
    device: str | None = None
    priority: TicketPriority | None = None
    analysis_priority: TicketPriority | None = None
    status: str
    analysis_summary: str | None = None
    analysis_confidence: int | None = None
    analysis_requires_human: bool | None = None
    analysis_requires_authorization: bool | None = None
    analysis_triggered_rules: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TicketUpdate(OrmModel):
    module: str | None = Field(default=None, max_length=80)
    priority: TicketPriority | None = None
    status: TicketStatus | None = None
    description: str | None = Field(default=None, min_length=5)
    ai_summary: str | None = None
