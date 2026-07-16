from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.customer import Customer, Establishment
from app.models.knowledge import TicketAnalysis
from app.models.messaging import Contact, ConversationSession, TemporaryCustomer
from app.models.product import Product
from app.models.ticket import Ticket, TicketStatus
from app.models.user import User
from app.repositories.crud import CrudRepository
from app.schemas.ticket import TicketCreate, TicketRead, TicketSummaryRead, TicketUpdate
from app.schemas.analysis import TicketAnalysisRead
from app.security.dependencies import get_current_user
from app.services.protocols import generate_ticket_protocol

router = APIRouter()
tickets = CrudRepository(Ticket)


def _summary_from_row(row) -> TicketSummaryRead:
    ticket = row[0]
    return TicketSummaryRead(
        id=ticket.id,
        protocol=ticket.protocol,
        customer_id=ticket.customer_id,
        customer_name=row.customer_name,
        contact_name=row.contact_name,
        company_name=row.company_name,
        phone=row.phone,
        product_id=ticket.product_id,
        product_name=row.product_name,
        analysis_product=row.analysis_product,
        system_name=row.system_name,
        module=row.analysis_module or ticket.module,
        device=row.analysis_device,
        priority=ticket.priority,
        analysis_priority=row.analysis_priority,
        status=ticket.status,
        analysis_summary=row.analysis_summary,
        analysis_confidence=row.analysis_confidence,
        analysis_requires_human=row.analysis_requires_human,
        analysis_requires_authorization=row.analysis_requires_authorization,
        analysis_triggered_rules=row.analysis_triggered_rules or [],
        created_at=ticket.opened_at,
        updated_at=row.analysis_updated_at or ticket.opened_at,
    )


@router.get("/", response_model=list[TicketSummaryRead])
def list_tickets(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    latest_analysis = (
        select(
            TicketAnalysis.ticket_id.label("ticket_id"),
            func.max(TicketAnalysis.created_at).label("created_at"),
        )
        .where(TicketAnalysis.tenant_id == current_user.tenant_id)
        .group_by(TicketAnalysis.ticket_id)
        .subquery()
    )
    stmt = (
        select(
            Ticket,
            Customer.name.label("customer_name"),
            Contact.name.label("contact_name"),
            TemporaryCustomer.company_name.label("company_name"),
            func.coalesce(Contact.phone, ConversationSession.phone, Customer.phone).label("phone"),
            Product.name.label("product_name"),
            TicketAnalysis.product.label("analysis_product"),
            TicketAnalysis.module.label("analysis_module"),
            TicketAnalysis.device.label("analysis_device"),
            TicketAnalysis.priority.label("analysis_priority"),
            TicketAnalysis.summary.label("analysis_summary"),
            TicketAnalysis.confidence.label("analysis_confidence"),
            TicketAnalysis.requires_human.label("analysis_requires_human"),
            TicketAnalysis.requires_authorization.label("analysis_requires_authorization"),
            TicketAnalysis.triggered_rules.label("analysis_triggered_rules"),
            TicketAnalysis.updated_at.label("analysis_updated_at"),
            func.coalesce(
                ConversationSession.collected_data["system_name"].as_string(),
                ConversationSession.collected_data["device_or_system"].as_string(),
                TemporaryCustomer.system_name,
                Customer.system_name,
            ).label("system_name"),
        )
        .select_from(Ticket)
        .outerjoin(Customer, and_(Customer.id == Ticket.customer_id, Customer.tenant_id == current_user.tenant_id))
        .outerjoin(Product, and_(Product.id == Ticket.product_id, Product.tenant_id == current_user.tenant_id))
        .outerjoin(ConversationSession, and_(ConversationSession.ticket_id == Ticket.id, ConversationSession.tenant_id == current_user.tenant_id))
        .outerjoin(Contact, and_(Contact.id == ConversationSession.contact_id, Contact.tenant_id == current_user.tenant_id))
        .outerjoin(TemporaryCustomer, and_(TemporaryCustomer.contact_id == Contact.id, TemporaryCustomer.tenant_id == current_user.tenant_id))
        .outerjoin(latest_analysis, latest_analysis.c.ticket_id == Ticket.id)
        .outerjoin(
            TicketAnalysis,
            and_(
                TicketAnalysis.ticket_id == Ticket.id,
                TicketAnalysis.tenant_id == current_user.tenant_id,
                TicketAnalysis.created_at == latest_analysis.c.created_at,
            ),
        )
        .where(Ticket.tenant_id == current_user.tenant_id)
        .order_by(Ticket.opened_at.desc())
    )
    return [_summary_from_row(row) for row in db.execute(stmt).all()]


@router.get("/{ticket_id}/analysis", response_model=TicketAnalysisRead)
def get_ticket_analysis(ticket_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    analysis = db.scalar(
        select(TicketAnalysis)
        .where(TicketAnalysis.ticket_id == ticket_id, TicketAnalysis.tenant_id == current_user.tenant_id)
        .order_by(TicketAnalysis.created_at.desc())
    )
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket analysis not found")
    return analysis


@router.post("/", response_model=TicketRead, status_code=201)
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    customer = db.scalar(select(Customer).where(Customer.id == payload.customer_id, Customer.tenant_id == current_user.tenant_id))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    if payload.establishment_id is not None:
        establishment = db.scalar(
            select(Establishment).where(
                Establishment.id == payload.establishment_id,
                Establishment.tenant_id == current_user.tenant_id,
                Establishment.customer_id == payload.customer_id,
            )
        )
        if establishment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Establishment not found")
    if payload.product_id is not None:
        product = db.scalar(select(Product).where(Product.id == payload.product_id, Product.tenant_id == current_user.tenant_id))
        if product is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    data = payload.model_dump()
    data["tenant_id"] = current_user.tenant_id
    data["protocol"] = generate_ticket_protocol()
    data["status"] = TicketStatus.NEW.value
    data["opened_at"] = datetime.now(UTC)
    return tickets.create(db, data)


@router.patch("/{ticket_id}", response_model=TicketRead)
def update_ticket(
    ticket_id: UUID,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = tickets.update_for_tenant(db, current_user.tenant_id, ticket_id, payload.model_dump(exclude_unset=True))
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket
