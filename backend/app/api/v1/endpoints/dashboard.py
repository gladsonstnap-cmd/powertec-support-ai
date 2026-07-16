from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.endpoints.tickets import list_tickets
from app.core.database import get_db
from app.models.user import User
from app.schemas.dashboard import DashboardSummary, DashboardTicket
from app.schemas.ticket import TicketSummaryRead
from app.security.dependencies import get_current_user

router = APIRouter()

PRIORITIES = ("P1", "P2", "P3", "P4")
STATUS_KEYS = ("new", "triage", "waiting_customer", "waiting_attendant", "in_progress", "resolved", "closed")
STATUS_ALIASES = {
    "novo": "new",
    "new": "new",
    "triagem": "triage",
    "triage": "triage",
    "aguardando_cliente": "waiting_customer",
    "waiting_customer": "waiting_customer",
    "waiting_attendant": "waiting_attendant",
    "em_atendimento": "in_progress",
    "in_progress": "in_progress",
    "resolvido": "resolved",
    "resolved": "resolved",
    "encerrado": "closed",
    "closed": "closed",
}
OPEN_STATUSES = {"new", "triage", "waiting_customer", "waiting_attendant", "in_progress"}


def _effective_priority(ticket: TicketSummaryRead) -> str:
    value = ticket.priority or ticket.analysis_priority or "P4"
    return value.value if hasattr(value, "value") else str(value)


def _normalized_status(status: str) -> str:
    return STATUS_ALIASES.get(status, status)


def _dashboard_ticket(ticket: TicketSummaryRead) -> DashboardTicket:
    return DashboardTicket(
        id=ticket.id,
        protocol=ticket.protocol,
        customer_name=ticket.customer_name,
        contact_name=ticket.contact_name,
        company_name=ticket.company_name,
        phone=ticket.phone,
        product_name=ticket.product_name,
        analysis_product=ticket.analysis_product,
        system_name=ticket.system_name,
        priority=ticket.priority,
        analysis_priority=ticket.analysis_priority,
        status=ticket.status,
        created_at=ticket.created_at,
        requires_human=bool(ticket.analysis_requires_human),
    )


def build_dashboard_summary(tickets: list[TicketSummaryRead], now: datetime | None = None) -> DashboardSummary:
    today = (now or datetime.now(UTC)).date()
    priority_counts = {priority: 0 for priority in PRIORITIES}
    status_counts = {status: 0 for status in STATUS_KEYS}
    open_tickets = 0
    resolved_today = 0
    human_required = 0
    for ticket in tickets:
        priority = _effective_priority(ticket)
        if priority in priority_counts:
            priority_counts[priority] += 1
        status = _normalized_status(ticket.status)
        if status in status_counts:
            status_counts[status] += 1
        if status in OPEN_STATUSES:
            open_tickets += 1
        if status == "resolved" and ticket.updated_at.date() == today:
            resolved_today += 1
        if ticket.analysis_requires_human:
            human_required += 1
    recent = sorted(tickets, key=lambda item: item.created_at, reverse=True)[:8]
    critical = [
        ticket
        for ticket in sorted(tickets, key=lambda item: (item.created_at), reverse=True)
        if _effective_priority(ticket) == "P1" and _normalized_status(ticket.status) not in {"resolved", "closed"}
    ][:5]
    return DashboardSummary(
        open_tickets=open_tickets,
        priority_counts=priority_counts,
        status_counts=status_counts,
        resolved_today=resolved_today,
        total_tickets=len(tickets),
        human_required=human_required,
        recent_tickets=[_dashboard_ticket(ticket) for ticket in recent],
        critical_tickets=[_dashboard_ticket(ticket) for ticket in critical],
    )


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return build_dashboard_summary(list_tickets(db, current_user))
