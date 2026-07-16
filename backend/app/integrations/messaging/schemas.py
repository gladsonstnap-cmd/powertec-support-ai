from pydantic import BaseModel, Field


class ProviderSendResult(BaseModel):
    provider: str
    external_message_id: str
    status: str = "sent"
    payload: dict = Field(default_factory=dict)
