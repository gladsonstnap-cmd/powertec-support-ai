import base64
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.integrations.messaging.exceptions import InvalidAttachmentError
from app.models.messaging import ConversationSession, MessageAttachment, MessagingMessage
from app.models.user import User
from app.schemas.messaging import AttachConversationRequest, ConversationRead, SendConversationMessageRequest, SimulateMessageRequest
from app.security.dependencies import get_current_user
from app.services.messaging.attachments import validate_attachment
from app.services.messaging.simulator import get_or_create_session, reset_session, send_initial_prompt, simulate_inbound_message

router = APIRouter()


def require_development() -> None:
    settings = get_settings()
    if settings.app_env != "development" or not settings.messaging_simulator_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulator is disabled")


def read_conversation(db: Session, tenant_id, session: ConversationSession) -> ConversationRead:
    messages = list(
        db.scalars(
            select(MessagingMessage)
            .where(MessagingMessage.session_id == session.id, MessagingMessage.tenant_id == tenant_id)
            .order_by(MessagingMessage.created_at)
        )
    )
    data = ConversationRead.model_validate(session)
    data.messages = messages
    return data


@router.post("/simulate", response_model=ConversationRead)
async def simulate_message(
    payload: SimulateMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_development()
    session = get_or_create_session(db, current_user.tenant_id, payload.phone)
    existing = db.scalar(select(MessagingMessage.id).where(MessagingMessage.session_id == session.id).limit(1))
    if existing is None:
        await send_initial_prompt(db, session)
    session = await simulate_inbound_message(
        db,
        current_user.tenant_id,
        payload.phone,
        payload.text or "",
        payload.message_type,
        payload.external_message_id,
    )
    return read_conversation(db, current_user.tenant_id, session)


@router.get("/conversations", response_model=list[ConversationRead])
def list_conversations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    require_development()
    sessions = list(
        db.scalars(
            select(ConversationSession)
            .where(ConversationSession.tenant_id == current_user.tenant_id)
            .order_by(ConversationSession.updated_at.desc().nullslast())
        )
    )
    return [read_conversation(db, current_user.tenant_id, session) for session in sessions]


@router.get("/conversations/{conversation_id}", response_model=ConversationRead)
def get_conversation(conversation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    require_development()
    session = db.scalar(
        select(ConversationSession).where(
            ConversationSession.id == conversation_id,
            ConversationSession.tenant_id == current_user.tenant_id,
        )
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return read_conversation(db, current_user.tenant_id, session)


@router.post("/conversations/{conversation_id}/reset", response_model=ConversationRead)
def reset_conversation(conversation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    require_development()
    try:
        session = reset_session(db, current_user.tenant_id, conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return read_conversation(db, current_user.tenant_id, session)


@router.post("/conversations/{conversation_id}/send", response_model=ConversationRead)
async def send_message(
    conversation_id: UUID,
    payload: SendConversationMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_development()
    session = db.scalar(select(ConversationSession).where(ConversationSession.id == conversation_id, ConversationSession.tenant_id == current_user.tenant_id))
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    session = await simulate_inbound_message(db, current_user.tenant_id, session.phone, payload.text, "text")
    return read_conversation(db, current_user.tenant_id, session)


@router.post("/conversations/{conversation_id}/attach", response_model=ConversationRead)
def attach_message(
    conversation_id: UUID,
    payload: AttachConversationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_development()
    session = db.scalar(select(ConversationSession).where(ConversationSession.id == conversation_id, ConversationSession.tenant_id == current_user.tenant_id))
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
        metadata = validate_attachment(payload.filename, payload.mime_type, content)
    except (ValueError, InvalidAttachmentError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    message = MessagingMessage(
        tenant_id=current_user.tenant_id,
        external_message_id=f"mock-in-attachment-{datetime.now(UTC).timestamp()}",
        provider="mock",
        direction="inbound",
        sender=session.phone,
        recipient="powertec",
        message_type="document",
        filename=payload.filename,
        mime_type=payload.mime_type,
        payload={"attachment": metadata},
        status="received",
        processing_status="processed",
        customer_id=session.customer_id,
        contact_id=session.contact_id,
        ticket_id=session.ticket_id,
        session_id=session.id,
        created_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
    )
    db.add(message)
    db.flush()
    db.add(
        MessageAttachment(
            tenant_id=current_user.tenant_id,
            message_id=message.id,
            media_id=message.external_message_id,
            created_at=datetime.now(UTC),
            **metadata,
        )
    )
    db.commit()
    return read_conversation(db, current_user.tenant_id, session)
