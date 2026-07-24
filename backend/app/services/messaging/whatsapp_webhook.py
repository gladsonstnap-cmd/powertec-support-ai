from datetime import UTC, datetime, timedelta

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


def _get_or_create_session(db: Session, tenant_id, contact: Contact, message: NormalizedWebhookMessage) -> tuple[ConversationSession, bool]:
    session = db.scalar(
        select(ConversationSession).where(
            ConversationSession.tenant_id == tenant_id,
            ConversationSession.phone == message.sender,
            ConversationSession.closed_at.is_(None),
        )
    )
    if session:
        return session, False
    session = ConversationSession(
        tenant_id=tenant_id,
        provider=message.provider,
        contact_id=contact.id,
        customer_id=contact.customer_id,
        phone=message.sender,
        current_state=ConversationState.WAITING_EQUIPMENT.value,
        collected_data={"source": "whatsapp_cloud_api"},
        priority_rules=[],
        unread_count=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(session)
    db.flush()
    return session, True


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


def register_event(
    db: Session,
    tenant_id,
    provider: str,
    event_type: str,
    payload: dict,
) -> None:
    db.add(
        MessagingEvent(
            tenant_id=tenant_id,
            provider=provider,
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(UTC),
        )
    )


def build_initial_response(contact_name: str | None, protocol: str) -> str:
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


generate_initial_response = build_initial_response


def build_ticket_summary(data: dict, protocol: str) -> str:
    return (
        "Resumo da solicitação:\n\n"
        f"Equipamento: {data.get('equipment') or '-'}\n"
        f"Problema: {data.get('problem') or '-'}\n"
        f"Início: {data.get('problem_started_at_text') or '-'}\n"
        f"Sinais observados: {data.get('symptoms') or '-'}\n\n"
        f"Protocolo: {protocol}\n\n"
        "Confirme com SIM ou informe o que deseja corrigir."
    )


def update_summary(session: ConversationSession) -> str:
    data = dict(session.collected_data or {})
    lines = []
    if data.get("equipment"):
        lines.append(f"Equipamento:\n{sanitize_text(data.get('equipment'))}")
    if data.get("problem"):
        lines.append(f"Problema:\n{sanitize_text(data.get('problem'))}")
    if data.get("problem_started_at_text"):
        lines.append(f"Início:\n{sanitize_text(data.get('problem_started_at_text'))}")
    if data.get("symptoms"):
        lines.append(f"Sintomas:\n{sanitize_text(data.get('symptoms'))}")
    summary = "\n\n".join(lines)
    data["conversation_summary"] = summary
    session.collected_data = data
    return summary


def apply_collected_data_to_ticket(ticket: Ticket, data: dict) -> None:
    equipment = sanitize_text(data.get("equipment"))
    problem = sanitize_text(data.get("problem"))
    started_at_text = sanitize_text(data.get("problem_started_at_text"))
    symptoms = sanitize_text(data.get("symptoms"))
    if equipment:
        ticket.module = equipment[:80]
    if problem:
        ticket.description = problem
    details = []
    if equipment:
        details.append(f"Equipamento: {equipment}")
    if problem:
        details.append(f"Problema: {problem}")
    if started_at_text:
        details.append(f"Início: {started_at_text}")
    if symptoms:
        details.append(f"Sinais observados: {symptoms}")
    if details:
        ticket.ai_summary = "Triagem determinística via WhatsApp.\n" + "\n".join(details)


def _change_state(db: Session, tenant_id, provider: str, session: ConversationSession, new_state: ConversationState, reason: str) -> None:
    previous = session.current_state
    session.current_state = new_state.value
    if previous != new_state.value:
        register_event(
            db,
            tenant_id,
            provider,
            "state_changed",
            {"from_state": previous, "to_state": new_state.value, "reason": reason, "session_id": str(session.id)},
        )


def close_session(db: Session, tenant_id, provider: str, session: ConversationSession, ticket: Ticket) -> str:
    _change_state(db, tenant_id, provider, session, ConversationState.CLOSED, "customer_cancelled")
    session.closed_at = datetime.now(UTC)
    ticket.status = TicketStatus.CANCELED.value
    register_event(db, tenant_id, provider, "conversation_closed", {"session_id": str(session.id), "ticket_id": str(ticket.id), "protocol": ticket.protocol})
    return f"Sua solicitação foi encerrada.\n\nCaso precise novamente, basta enviar uma nova mensagem.\n\nProtocolo:\n{ticket.protocol}"


def restart_session(db: Session, tenant_id, provider: str, session: ConversationSession, ticket: Ticket, contact_name: str | None) -> str:
    session.collected_data = {"source": "whatsapp_cloud_api", "conversation_restarted_at": datetime.now(UTC).isoformat()}
    session.protocol = ticket.protocol
    _change_state(db, tenant_id, provider, session, ConversationState.WAITING_EQUIPMENT, "customer_restarted")
    register_event(db, tenant_id, provider, "conversation_restarted", {"session_id": str(session.id), "ticket_id": str(ticket.id), "protocol": ticket.protocol})
    return build_initial_response(contact_name, ticket.protocol)


def forward_to_attendant(db: Session, tenant_id, provider: str, session: ConversationSession, ticket: Ticket) -> str:
    _change_state(db, tenant_id, provider, session, ConversationState.READY_FOR_ATTENDANT, "customer_requested_human")
    ticket.status = TicketStatus.IN_SERVICE.value
    register_event(db, tenant_id, provider, "conversation_forwarded", {"session_id": str(session.id), "ticket_id": str(ticket.id), "protocol": ticket.protocol})
    return f"Seu atendimento foi encaminhado para nossa equipe técnica.\n\nProtocolo:\n{ticket.protocol}"


def handle_status(db: Session, tenant_id, provider: str, session: ConversationSession, ticket: Ticket) -> str:
    now = datetime.now(UTC)
    opened_at = ticket.opened_at
    elapsed = now - opened_at if opened_at else timedelta()
    register_event(db, tenant_id, provider, "status_requested", {"session_id": str(session.id), "ticket_id": str(ticket.id), "protocol": ticket.protocol})
    return (
        f"Protocolo: {ticket.protocol}\n"
        f"Estado atual: {session.current_state}\n"
        f"Prioridade: {ticket.priority}\n"
        f"Data abertura: {opened_at.isoformat() if opened_at else '-'}\n"
        f"Tempo em atendimento: {int(elapsed.total_seconds() // 60)} minutos"
    )


def handle_correction(db: Session, tenant_id, provider: str, session: ConversationSession, text: str) -> str | None:
    normalized = text.strip().lower()
    mapping = {
        "corrigir equipamento": (ConversationState.WAITING_EQUIPMENT, "Informe novamente qual é o equipamento."),
        "corrigir problema": (ConversationState.WAITING_PROBLEM, "Descreva novamente qual problema o equipamento apresenta."),
        "corrigir início": (ConversationState.WAITING_DATE, "Informe novamente quando o problema começou."),
        "corrigir inicio": (ConversationState.WAITING_DATE, "Informe novamente quando o problema começou."),
        "corrigir data": (ConversationState.WAITING_DATE, "Informe novamente quando o problema começou."),
        "corrigir sintomas": (ConversationState.WAITING_SYMPTOMS, "Informe novamente os sinais observados."),
    }
    if normalized not in mapping:
        return None
    state, response = mapping[normalized]
    _change_state(db, tenant_id, provider, session, state, "customer_corrected_information")
    register_event(db, tenant_id, provider, "customer_corrected_information", {"session_id": str(session.id), "field": normalized.replace("corrigir ", "")})
    return response


def handle_global_commands(db: Session, tenant_id, provider: str, session: ConversationSession, ticket: Ticket, text: str, contact_name: str | None) -> str | None:
    normalized = text.strip().lower()
    if normalized in {"cancelar", "cancelar atendimento", "encerrar"}:
        return close_session(db, tenant_id, provider, session, ticket)
    if normalized in {"reiniciar", "reiniciar atendimento", "novo atendimento"}:
        return restart_session(db, tenant_id, provider, session, ticket, contact_name)
    if normalized in {"atendente", "humano", "falar com atendente"}:
        return forward_to_attendant(db, tenant_id, provider, session, ticket)
    if normalized == "status":
        return handle_status(db, tenant_id, provider, session, ticket)
    return handle_correction(db, tenant_id, provider, session, normalized)


def is_session_expired(session: ConversationSession, now: datetime | None = None, timeout_minutes: int = 60) -> bool:
    if session.closed_at or not session.updated_at:
        return False
    current_time = now or datetime.now(UTC)
    return current_time - session.updated_at > timedelta(minutes=timeout_minutes)


def mark_waiting_customer(db: Session, tenant_id, provider: str, session: ConversationSession) -> str:
    _change_state(db, tenant_id, provider, session, ConversationState.WAITING_CUSTOMER, "session_timeout")
    return "Seu atendimento ficou pausado.\n\nCaso deseje continuar basta responder esta mensagem."


def resume_session(db: Session, tenant_id, provider: str, session: ConversationSession) -> None:
    if session.current_state == ConversationState.WAITING_CUSTOMER.value:
        _change_state(db, tenant_id, provider, session, ConversationState.WAITING_EQUIPMENT, "customer_resumed")


def handle_conversation_state(
    db: Session,
    tenant_id,
    provider: str,
    session: ConversationSession,
    ticket: Ticket,
    inbound_text: str,
    is_new_session: bool,
    contact_name: str | None,
) -> str:
    data = dict(session.collected_data or {})
    text = sanitize_text(inbound_text)
    if is_new_session:
        _change_state(db, tenant_id, provider, session, ConversationState.WAITING_EQUIPMENT, "new_whatsapp_session")
        session.collected_data = data
        apply_collected_data_to_ticket(ticket, data)
        return build_initial_response(contact_name, ticket.protocol)

    command_response = handle_global_commands(db, tenant_id, provider, session, ticket, text, contact_name)
    if command_response:
        return command_response
    if is_session_expired(session):
        return mark_waiting_customer(db, tenant_id, provider, session)
    if session.current_state == ConversationState.WAITING_CUSTOMER.value:
        resume_session(db, tenant_id, provider, session)

    current_state = ConversationState(session.current_state)
    if current_state == ConversationState.WAITING_EQUIPMENT:
        data["equipment"] = text
        _change_state(db, tenant_id, provider, session, ConversationState.WAITING_PROBLEM, "equipment_collected")
        response = "Qual problema o equipamento apresenta?"
    elif current_state == ConversationState.WAITING_PROBLEM:
        data["problem"] = text
        _change_state(db, tenant_id, provider, session, ConversationState.WAITING_DATE, "problem_collected")
        response = "Quando o problema começou?"
    elif current_state == ConversationState.WAITING_DATE:
        data["problem_started_at_text"] = text
        _change_state(db, tenant_id, provider, session, ConversationState.WAITING_SYMPTOMS, "problem_start_collected")
        response = "Existe algum sinal visível, como LED aceso, bip, tela, barulho ou cheiro de queimado?"
    elif current_state == ConversationState.WAITING_SYMPTOMS:
        data["symptoms"] = text
        _change_state(db, tenant_id, provider, session, ConversationState.WAITING_CONFIRMATION, "symptoms_collected")
        response = build_ticket_summary(data, ticket.protocol)
    elif current_state == ConversationState.WAITING_CONFIRMATION:
        if text.strip().lower() == "sim":
            _change_state(db, tenant_id, provider, session, ConversationState.READY_FOR_ATTENDANT, "customer_confirmed_summary")
            ticket.status = TicketStatus.IN_SERVICE.value
            response = f"Solicitação confirmada e encaminhada para atendimento humano.\n\nProtocolo: {ticket.protocol}"
        else:
            data["correction_request"] = text
            _change_state(db, tenant_id, provider, session, ConversationState.WAITING_PROBLEM, "customer_requested_correction")
            response = "Qual informação deseja corrigir? Descreva o problema atualizado."
    else:
        response = f"Recebemos sua atualização no protocolo {ticket.protocol}. A solicitação permanece em atendimento."
    session.collected_data = data
    apply_collected_data_to_ticket(ticket, data)
    update_summary(session)
    register_event(db, tenant_id, provider, "summary_updated", {"session_id": str(session.id), "summary": session.collected_data.get("conversation_summary", "")})
    return response


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
        session, is_new_session = _get_or_create_session(db, tenant_id, contact, message)
        ticket = _ensure_ticket(db, tenant_id, session, contact, message)
        response_text = handle_conversation_state(db, tenant_id, message.provider, session, ticket, valid_text, is_new_session, contact.name)
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
                "response_text": response_text,
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
