from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.messaging.schemas import NormalizedWebhookMessage
from app.integrations.messaging.exceptions import MessagingError
from app.models.customer import Customer
from app.models.messaging import Contact, ConversationSession, ConversationState, MessagingEvent, MessagingMessage, TicketMessage
from app.models.tenant import Tenant
from app.models.ticket import Ticket, TicketStatus
from app.services.messaging.classifier import classify_problem
from app.services.messaging.protocols import generate_protocol
from app.services.messaging.security import sanitize_text


def default_webhook_tenant_id(db: Session):
    tenant = db.scalar(select(Tenant).where(Tenant.is_active.is_(True)).order_by(Tenant.created_at).limit(1))
    if tenant is None:
        return None
    return tenant.id


def _parse_timestamp(value: str | None) -> datetime:
    if value and value.isdigit():
        return datetime.fromtimestamp(int(value), UTC)
    return datetime.now(UTC)


def _get_or_create_contact(db: Session, tenant_id, message: NormalizedWebhookMessage) -> Contact:
    contact = db.scalar(select(Contact).where(Contact.tenant_id == tenant_id, Contact.phone == message.sender))
    if contact:
        if message.contact_name and not contact.name:
            contact.name = message.contact_name
        return contact
    contact = Contact(
        tenant_id=tenant_id,
        phone=message.sender,
        name=message.contact_name,
        is_temporary=True,
        validation_status="pending",
        created_at=datetime.now(UTC),
    )
    db.add(contact)
    db.flush()
    return contact


def _get_or_create_session(db: Session, tenant_id, contact: Contact, message: NormalizedWebhookMessage) -> ConversationSession:
    session = db.scalar(
        select(ConversationSession).where(
            ConversationSession.tenant_id == tenant_id,
            ConversationSession.phone == message.sender,
            ConversationSession.closed_at.is_(None),
        )
    )
    if session:
        return session
    session = ConversationSession(
        tenant_id=tenant_id,
        provider=message.provider,
        contact_id=contact.id,
        customer_id=contact.customer_id,
        phone=message.sender,
        current_state=ConversationState.WAITING_ATTENDANT.value,
        collected_data={"source": "whatsapp_cloud_api"},
        priority_rules=[],
        unread_count=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(session)
    db.flush()
    return session


def _ensure_customer(db: Session, tenant_id, contact: Contact, message: NormalizedWebhookMessage) -> Customer:
    if contact.customer_id:
        customer = db.get(Customer, contact.customer_id)
        if customer:
            return customer
    customer = Customer(
        tenant_id=tenant_id,
        name=message.contact_name or f"Contato WhatsApp {message.sender}",
        phone=message.sender,
        is_active=False,
    )
    db.add(customer)
    db.flush()
    contact.customer_id = customer.id
    return customer


def _ensure_ticket(db: Session, tenant_id, session: ConversationSession, contact: Contact, message: NormalizedWebhookMessage) -> Ticket:
    if session.ticket_id:
        ticket = db.get(Ticket, session.ticket_id)
        if ticket and ticket.closed_at is None and ticket.status not in {TicketStatus.CLOSED.value, TicketStatus.CANCELED.value}:
            return ticket
    customer = _ensure_customer(db, tenant_id, contact, message)
    text = sanitize_text(message.text or "")
    classification = classify_problem(text)
    protocol = generate_protocol(db, tenant_id)
    ticket = Ticket(
        tenant_id=tenant_id,
        protocol=protocol,
        customer_id=customer.id,
        priority=classification.priority,
        status=TicketStatus.NEW.value,
        description=text,
        ai_summary=f"Ticket criado a partir do webhook WhatsApp. Regras: {', '.join(classification.rules) or 'nenhuma'}.",
        opened_at=datetime.now(UTC),
    )
    db.add(ticket)
    db.flush()
    session.ticket_id = ticket.id
    session.customer_id = customer.id
    session.protocol = protocol
    session.preliminary_priority = classification.priority
    session.priority_rules = classification.rules
    db.add(TicketMessage(tenant_id=tenant_id, ticket_id=ticket.id, body=text, internal_note=False, created_at=datetime.now(UTC)))
    return ticket


def generate_initial_response(contact_name: str | None, protocol: str) -> str:
    if contact_name:
        greeting = f"Olá, {contact_name}. Recebemos sua solicitação na PowerTec."
    else:
        greeting = "Olá! Recebemos sua solicitação na PowerTec."
    return (
        f"{greeting}\n\n"
        f"Protocolo: {protocol}\n\n"
        "Descreva com mais detalhes:\n"
        "1 - Qual é o equipamento?\n"
        "2 - Qual problema está apresentando?\n"
        "3 - Quando o problema começou?"
    )


def process_normalized_messages(db: Session, tenant_id, messages: list[NormalizedWebhookMessage]) -> dict:
    processed = 0
    duplicates = 0
    unsupported = 0
    response_candidates = []
    for message in messages:
        valid_text = sanitize_text(message.text)
        if not message.supported or not valid_text:
            unsupported += 1
            db.add(
                MessagingEvent(
                    tenant_id=tenant_id,
                    provider=message.provider,
                    event_type="unsupported_message" if message.supported else "unsupported_message",
                    payload={"external_message_id": message.external_message_id, "reason": message.unsupported_reason or "empty text"},
                    created_at=datetime.now(UTC),
                )
            )
            continue
        existing = db.scalar(
            select(MessagingMessage).where(
                MessagingMessage.tenant_id == tenant_id,
                MessagingMessage.provider == message.provider,
                MessagingMessage.external_message_id == message.external_message_id,
            )
        )
        if existing:
            duplicates += 1
            continue
        contact = _get_or_create_contact(db, tenant_id, message)
        session = _get_or_create_session(db, tenant_id, contact, message)
        ticket = _ensure_ticket(db, tenant_id, session, contact, message)
        inbound = MessagingMessage(
            tenant_id=tenant_id,
            external_message_id=message.external_message_id,
            provider=message.provider,
            direction="inbound",
            sender=message.sender,
            recipient=message.recipient,
            message_type=message.message_type,
            text_content=valid_text,
            payload=message.raw_payload,
            status="received",
            processing_status="processed",
            customer_id=session.customer_id,
            contact_id=contact.id,
            ticket_id=ticket.id,
            session_id=session.id,
            created_at=datetime.now(UTC),
            received_at=_parse_timestamp(message.timestamp),
        )
        db.add(inbound)
        session.unread_count += 1
        session.updated_at = datetime.now(UTC)
        processed += 1
        response_candidates.append(
            {
                "message": message,
                "inbound": inbound,
                "ticket": ticket,
                "session": session,
                "contact": contact,
                "customer_id": session.customer_id,
                "response_text": generate_initial_response(contact.name, ticket.protocol),
            }
        )
    db.commit()
    return {"processed": processed, "duplicates": duplicates, "unsupported": unsupported, "response_candidates": response_candidates}


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, MessagingError):
        return str(exc)[:300]
    return exc.__class__.__name__


async def send_text_response(
    db: Session,
    tenant_id,
    recipient: str,
    text: str,
    provider,
    *,
    ticket_id=None,
    session_id=None,
    contact_id=None,
    customer_id=None,
) -> MessagingMessage:
    result = await provider.send_text(recipient, text)
    outbound = MessagingMessage(
        tenant_id=tenant_id,
        external_message_id=result["external_message_id"],
        provider=result.get("provider", getattr(provider, "provider_name", "unknown")),
        direction="outbound",
        sender="powertec",
        recipient=recipient,
        message_type="text",
        text_content=sanitize_text(text),
        payload=result,
        status=result.get("status", "sent"),
        processing_status="processed",
        customer_id=customer_id,
        contact_id=contact_id,
        ticket_id=ticket_id,
        session_id=session_id,
        created_at=datetime.now(UTC),
        sent_at=datetime.now(UTC),
    )
    db.add(outbound)
    db.commit()
    return outbound


async def send_automatic_responses(db: Session, tenant_id, response_candidates: list[dict], provider) -> dict:
    sent = 0
    failed = 0
    for candidate in response_candidates:
        message = candidate["message"]
        ticket = candidate["ticket"]
        session = candidate["session"]
        contact = candidate["contact"]
        text = candidate["response_text"]
        if not text or not ticket or not session or not contact:
            continue
        try:
            await send_text_response(
                db,
                tenant_id,
                message.sender,
                text,
                provider,
                ticket_id=ticket.id,
                session_id=session.id,
                contact_id=contact.id,
                customer_id=candidate["customer_id"],
            )
            sent += 1
        except Exception as exc:
            failed += 1
            db.add(
                MessagingEvent(
                    tenant_id=tenant_id,
                    provider=getattr(provider, "provider_name", message.provider),
                    event_type="automatic_response_failed",
                    payload={
                        "external_message_id": message.external_message_id,
                        "ticket_id": str(ticket.id),
                        "error": _safe_error_message(exc),
                    },
                    created_at=datetime.now(UTC),
                )
            )
            db.commit()
    return {"automatic_responses_sent": sent, "automatic_responses_failed": failed}


async def process_messages_and_send_initial_response(db: Session, tenant_id, messages: list[NormalizedWebhookMessage], provider) -> dict:
    result = process_normalized_messages(db, tenant_id, messages)
    response_result = await send_automatic_responses(db, tenant_id, result.pop("response_candidates", []), provider)
    return {**result, **response_result}
