from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.support.agent import AGENT_VERSION, SupportAgent, analysis_to_record_kwargs
from app.agents.support.safety import safe_customer_response
from app.core.config import get_settings
from app.integrations.messaging.factory import get_messaging_provider
from app.models.customer import Customer, Establishment
from app.models.knowledge import SupportAuditLog, TicketAnalysis
from app.models.messaging import (
    Contact,
    ConversationSession,
    ConversationState,
    ConversationStateTransition,
    MessagingMessage,
    TemporaryCustomer,
    TicketMessage,
)
from app.models.ticket import Ticket, TicketStatus
from app.services.messaging.classifier import classify_problem
from app.services.messaging.protocols import generate_protocol
from app.services.messaging.security import sanitize_text
from app.services.messaging import templates


class ConversationStateMachine:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.provider = get_messaging_provider()

    async def process_message(self, session: ConversationSession, message: MessagingMessage) -> list[MessagingMessage]:
        text = sanitize_text(message.text_content)
        replies: list[str] = []
        current = ConversationState(session.current_state)
        data = dict(session.collected_data or {})

        if text.lower() == "falar com atendente":
            self._transition(session, current, ConversationState.WAITING_ATTENDANT, message, "manual_handoff")
            replies.append(templates.ATTENDANT)
            return await self._persist_replies(session, message, replies)

        if current == ConversationState.CONFIRMING_CUSTOMER:
            self._transition(session, current, ConversationState.SELECTING_DEVICE, message, "customer_confirmed")
            replies.append(templates.ASK_DEVICE)
        elif current == ConversationState.REQUESTING_CONTACT_NAME:
            data["contact_name"] = text
            self._transition(session, current, ConversationState.REQUESTING_COMPANY, message, "collected_contact_name")
            replies.append(templates.ASK_COMPANY)
        elif current == ConversationState.REQUESTING_COMPANY:
            data["company_name"] = text
            self._transition(session, current, ConversationState.REQUESTING_CITY, message, "collected_company")
            replies.append(templates.ASK_CITY)
        elif current == ConversationState.REQUESTING_CITY:
            data["city"] = text
            self._transition(session, current, ConversationState.REQUESTING_SYSTEM, message, "collected_city")
            replies.append(templates.ASK_SYSTEM)
        elif current == ConversationState.REQUESTING_SYSTEM:
            data["system_name"] = text
            self._upsert_temporary_customer(session, data)
            self._transition(session, current, ConversationState.COLLECTING_PROBLEM, message, "temporary_customer_created")
            replies.append(templates.ASK_PROBLEM)
        elif current in {ConversationState.SELECTING_DEVICE, ConversationState.COLLECTING_PROBLEM}:
            if current == ConversationState.SELECTING_DEVICE:
                data["device_or_system"] = text
                self._transition(session, current, ConversationState.COLLECTING_PROBLEM, message, "device_selected")
                replies.append(templates.ASK_PROBLEM)
            else:
                protocol, customer_reply = await self._create_ticket(session, text)
                self._transition(session, current, ConversationState.TICKET_CREATED, message, "ticket_created")
                replies.append(templates.TICKET_CREATED.format(protocol=protocol))
                replies.append(customer_reply)
        else:
            replies.append("Recebi sua mensagem. Para reiniciar o atendimento, use a opcao de reinicio no simulador.")

        session.collected_data = data
        session.updated_at = datetime.now(UTC)
        self.db.flush()
        return await self._persist_replies(session, message, replies)

    def _transition(
        self,
        session: ConversationSession,
        from_state: ConversationState,
        to_state: ConversationState,
        message: MessagingMessage | None,
        reason: str,
    ) -> None:
        session.current_state = to_state.value
        session.updated_at = datetime.now(UTC)
        self.db.add(
            ConversationStateTransition(
                tenant_id=session.tenant_id,
                session_id=session.id,
                from_state=from_state.value,
                to_state=to_state.value,
                message_id=message.id if message else None,
                reason=reason,
                created_at=datetime.now(UTC),
            )
        )

    def _upsert_temporary_customer(self, session: ConversationSession, data: dict) -> None:
        existing = self.db.scalar(select(TemporaryCustomer).where(TemporaryCustomer.contact_id == session.contact_id))
        if existing is None:
            self.db.add(
                TemporaryCustomer(
                    tenant_id=session.tenant_id,
                    contact_id=session.contact_id,
                    contact_name=data.get("contact_name"),
                    company_name=data.get("company_name"),
                    city=data.get("city"),
                    system_name=data.get("system_name"),
                    created_at=datetime.now(UTC),
                )
            )
        else:
            existing.contact_name = data.get("contact_name")
            existing.company_name = data.get("company_name")
            existing.city = data.get("city")
            existing.system_name = data.get("system_name")

    async def _create_ticket(self, session: ConversationSession, description: str) -> tuple[str, str]:
        classification = classify_problem(description)
        protocol = generate_protocol(self.db, session.tenant_id)
        customer_id = session.customer_id
        if customer_id is None:
            customer = Customer(
                tenant_id=session.tenant_id,
                name=session.collected_data.get("company_name", "Cliente temporario"),
                city=session.collected_data.get("city"),
                system_name=session.collected_data.get("system_name"),
                is_active=False,
            )
            self.db.add(customer)
            self.db.flush()
            customer_id = customer.id
            session.customer_id = customer_id
        ticket = Ticket(
            tenant_id=session.tenant_id,
            protocol=protocol,
            customer_id=customer_id,
            establishment_id=session.establishment_id,
            product_id=session.product_id,
            priority=classification.priority,
            status=TicketStatus.NEW.value,
            description=description,
            ai_summary=f"Triagem preliminar deterministica. Regras: {', '.join(classification.rules) or 'nenhuma'}.",
            opened_at=datetime.now(UTC),
        )
        self.db.add(ticket)
        self.db.flush()
        session.ticket_id = ticket.id
        session.protocol = protocol
        session.preliminary_priority = classification.priority
        session.priority_rules = classification.rules
        self.db.add(
            TicketMessage(
                tenant_id=session.tenant_id,
                ticket_id=ticket.id,
                body=description,
                internal_note=False,
                created_at=datetime.now(UTC),
            )
        )
        analysis = await SupportAgent(self.db).analyze_ticket(
            ticket,
            [type("MessageContext", (), {"text_content": description})()],
            {
                "product": session.collected_data.get("device_or_system"),
                "previous_questions": session.collected_data.get("_questions", []),
                "question_count": session.collected_data.get("_question_count", 0),
            },
        )
        ticket.priority = analysis.priority
        ticket.ai_summary = analysis.summary
        session.preliminary_priority = analysis.priority
        session.priority_rules = analysis.triggered_rules
        analysis_record = TicketAnalysis(**analysis_to_record_kwargs(analysis, session.tenant_id, ticket.id, get_settings().ai_provider))
        self.db.add(analysis_record)
        self.db.flush()
        document_ids = [source.document_id for source in analysis.knowledge_sources]
        question = analysis.suggested_questions[0] if analysis.suggested_questions else None
        customer_reply = safe_customer_response(question, analysis.priority, analysis.requires_human)
        data = dict(session.collected_data or {})
        if question:
            questions = list(data.get("_questions", []))
            questions.append(question)
            data["_questions"] = questions[-10:]
            data["_question_count"] = int(data.get("_question_count", 0)) + 1
        session.collected_data = data
        self.db.add(
            SupportAuditLog(
                tenant_id=session.tenant_id,
                ticket_id=ticket.id,
                analysis_id=analysis_record.id,
                event_type="analysis_executed",
                agent_version=AGENT_VERSION,
                provider=analysis_record.provider,
                triggered_rules=analysis.triggered_rules,
                document_ids=document_ids,
                result={
                    "priority": analysis.priority,
                    "requires_human": analysis.requires_human,
                    "requires_authorization": analysis.requires_authorization,
                },
                customer_response=customer_reply,
                created_at=datetime.now(UTC),
            )
        )
        return protocol, customer_reply

    async def _persist_replies(
        self,
        session: ConversationSession,
        source_message: MessagingMessage,
        replies: list[str],
    ) -> list[MessagingMessage]:
        saved: list[MessagingMessage] = []
        for reply in replies:
            result = await self.provider.send_text(source_message.sender, reply)
            outbound = MessagingMessage(
                tenant_id=session.tenant_id,
                external_message_id=result["external_message_id"],
                provider=result.get("provider", getattr(self.provider, "provider_name", "mock")),
                direction="outbound",
                sender=source_message.recipient,
                recipient=source_message.sender,
                message_type="text",
                text_content=reply,
                payload=result,
                status="sent",
                processing_status="processed",
                customer_id=session.customer_id,
                contact_id=session.contact_id,
                ticket_id=session.ticket_id,
                session_id=session.id,
                created_at=datetime.now(UTC),
                sent_at=datetime.now(UTC),
            )
            self.db.add(outbound)
            saved.append(outbound)
        return saved
