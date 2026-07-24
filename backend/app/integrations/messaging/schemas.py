from pydantic import BaseModel, Field


class ProviderSendResult(BaseModel):
    provider: str
    external_message_id: str
    status: str = "sent"
    payload: dict = Field(default_factory=dict)


class NormalizedWebhookMessage(BaseModel):
    provider: str
    external_message_id: str
    sender: str
    recipient: str
    message_type: str
    text: str | None = None
    timestamp: str | None = None
    contact_name: str | None = None
    raw_payload: dict = Field(default_factory=dict)
    supported: bool = True
    unsupported_reason: str | None = None
