from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.customer import Customer, Establishment
from app.models.messaging import Contact, ConversationSession, ConversationState, MessagingMessage
from app.services.messaging.security import sanitize_text
from app.services.messaging.state_machine import ConversationStateMachine
from app.services.messaging import templates


def get_or_create_session(db: Session, tenant_id, phone: str) -> ConversationSession:
    session = db.scalar(
        select(ConversationSession).where(
            ConversationSession.tenant_id == tenant_id,
            ConversationSession.phone == phone,
            ConversationSession.closed_at.is_(None),
        )
    )
    if session:
        return session

    contact = db.scalar(select(Contact).where(Contact.tenant_id == tenant_id, Contact.phone == phone))
    state = ConversationState.CONFIRMING_CUSTOMER if contact and not contact.is_temporary else ConversationState.REQUESTING_CONTACT_NAME
    session = ConversationSession(
        tenant_id=tenant_id,
        provider="mock",
        contact_id=contact.id if contact else None,
        customer_id=contact.customer_id if contact else None,
        phone=phone,
        current_state=state.value,
        collected_data={},
        priority_rules=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    if contact and contact.customer_id:
        establishment = db.scalar(select(Establishment).where(Establishment.customer_id == contact.customer_id))
        session.establishment_id = establishment.id if establishment else None
    elif contact is None:
        contact = Contact(
            tenant_id=tenant_id,
            phone=phone,
            is_temporary=True,
            validation_status="pending",
            created_at=datetime.now(UTC),
        )
        db.add(contact)
        db.flush()
        session.contact_id = contact.id
    db.add(session)
    db.flush()
    return session


async def simulate_inbound_message(
    db: Session,
    tenant_id,
    phone: str,
    text: str | None,
    message_type: str = "text",
    external_message_id: str | None = None,
) -> ConversationSession:
    session = get_or_create_session(db, tenant_id, phone)
    external_id = external_message_id or f"mock-in-{uuid4()}"
    message = MessagingMessage(
        tenant_id=tenant_id,
        external_message_id=external_id,
        provider="mock",
        direction="inbound",
        sender=phone,
        recipient="powertec",
        message_type=message_type,
        text_content=sanitize_text(text),
        payload={"source": "simulator"},
        status="received",
        processing_status="processing",
        customer_id=session.customer_id,
        contact_id=session.contact_id,
        session_id=session.id,
        created_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
    )
    db.add(message)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return get_or_create_session(db, tenant_id, phone)

    if message_type == "text":
        machine = ConversationStateMachine(db)
        await machine.process_message(session, message)
    message.processing_status = "processed"
    db.commit()
    db.refresh(session)
    return session


def reset_session(db: Session, tenant_id, session_id) -> ConversationSession:
    session = db.scalar(select(ConversationSession).where(ConversationSession.id == session_id, ConversationSession.tenant_id == tenant_id))
    if session is None:
        raise ValueError("Conversation not found")
    session.current_state = ConversationState.REQUESTING_CONTACT_NAME.value if session.customer_id is None else ConversationState.CONFIRMING_CUSTOMER.value
    session.collected_data = {}
    session.preliminary_priority = None
    session.priority_rules = []
    session.ticket_id = None
    session.protocol = None
    session.unread_count = 0
    session.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(session)
    return session


async def send_initial_prompt(db: Session, session: ConversationSession) -> None:
    if session.customer_id:
        contact = db.scalar(select(Contact).where(Contact.id == session.contact_id))
        customer = db.scalar(select(Customer).where(Customer.id == session.customer_id))
        establishment = db.scalar(select(Establishment).where(Establishment.id == session.establishment_id))
        text = templates.WELCOME_KNOWN.format(
            name=contact.name or "cliente",
            company=customer.name if customer else "sua empresa",
            establishment=establishment.name if establishment else "loja encontrada",
        )
    else:
        text = templates.WELCOME_UNKNOWN
    msg = MessagingMessage(
        tenant_id=session.tenant_id,
        external_message_id=f"mock-out-{uuid4()}",
        provider="mock",
        direction="outbound",
        sender="powertec",
        recipient=session.phone,
        message_type="text",
        text_content=text,
        payload={},
        status="sent",
        processing_status="processed",
        contact_id=session.contact_id,
        customer_id=session.customer_id,
        session_id=session.id,
        created_at=datetime.now(UTC),
        sent_at=datetime.now(UTC),
    )
    db.add(msg)
    db.commit()
