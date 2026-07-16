from pydantic import BaseModel, Field


class MockInboundMessage(BaseModel):
    phone: str = Field(min_length=8, max_length=32)
    text: str | None = Field(default=None, max_length=2000)
    message_type: str = "text"
    external_message_id: str | None = None
