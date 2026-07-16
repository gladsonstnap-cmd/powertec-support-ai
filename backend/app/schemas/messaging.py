from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SimulateMessageRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=32)
    text: str | None = Field(default=None, max_length=2000)
    message_type: str = "text"
    external_message_id: str | None = None


class SendConversationMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class AttachConversationRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    mime_type: str = Field(min_length=3, max_length=120)
    content_base64: str = Field(min_length=1)


class MessagingMessageRead(BaseModel):
    id: UUID
    direction: str
    sender: str
    recipient: str
    message_type: str
    text_content: str | None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationRead(BaseModel):
    id: UUID
    phone: str
    current_state: str
    collected_data: dict
    preliminary_priority: str | None
    priority_rules: list
    protocol: str | None
    ticket_id: UUID | None
    customer_id: UUID | None
    contact_id: UUID | None
    unread_count: int
    created_at: datetime
    messages: list[MessagingMessageRead] = []

    class Config:
        from_attributes = True
