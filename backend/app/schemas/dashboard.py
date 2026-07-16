from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.ticket import TicketPriority


class DashboardTicket(BaseModel):
    id: UUID
    protocol: str
    customer_name: str | None = None
    contact_name: str | None = None
    company_name: str | None = None
    phone: str | None = None
    product_name: str | None = None
    analysis_product: str | None = None
    system_name: str | None = None
    priority: TicketPriority | None = None
    analysis_priority: TicketPriority | None = None
    status: str
    created_at: datetime
    requires_human: bool = False


class DashboardSummary(BaseModel):
    open_tickets: int
    priority_counts: dict[str, int]
    status_counts: dict[str, int]
    resolved_today: int
    total_tickets: int
    human_required: int
    recent_tickets: list[DashboardTicket]
    critical_tickets: list[DashboardTicket]
