from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.dev_messaging import read_conversation
from app.core.database import get_db
from app.models.messaging import ConversationSession
from app.models.user import User
from app.schemas.messaging import ConversationRead
from app.security.dependencies import get_current_user

router = APIRouter()


@router.get("/", response_model=list[ConversationRead])
def list_conversations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    sessions = list(
        db.scalars(
            select(ConversationSession)
            .where(ConversationSession.tenant_id == current_user.tenant_id)
            .order_by(ConversationSession.updated_at.desc().nullslast())
        )
    )
    return [read_conversation(db, current_user.tenant_id, session) for session in sessions]


@router.get("/{conversation_id}", response_model=ConversationRead)
def get_conversation(conversation_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = db.scalar(
        select(ConversationSession).where(
            ConversationSession.id == conversation_id,
            ConversationSession.tenant_id == current_user.tenant_id,
        )
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return read_conversation(db, current_user.tenant_id, session)
