from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


class TicketPriority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class TicketStatus(StrEnum):
    NEW = "novo"
    TRIAGE = "triagem"
    WAITING_CUSTOMER = "aguardando_cliente"
    IN_SERVICE = "em_atendimento"
    RESOLVED = "resolvido"
    CLOSED = "encerrado"
    CANCELED = "cancelado"


class Ticket(IdMixin, Base):
    __tablename__ = "tickets"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    protocol: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    establishment_id: Mapped[UUID | None] = mapped_column(ForeignKey("establishments.id"))
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"))
    module: Mapped[str | None] = mapped_column(String(80))
    priority: Mapped[str] = mapped_column(String(2), default=TicketPriority.P4.value, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=TicketStatus.NEW.value, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
