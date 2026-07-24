from app.integrations.messaging.base import MessagingProvider
from app.integrations.messaging.mock.storage import MEDIA, record_outbound


class MockMessagingProvider(MessagingProvider):
    provider_name = "mock"

    async def send_text(self, recipient: str, text: str) -> dict:
        return record_outbound("text", recipient, {"text": text})

    async def send_buttons(self, recipient: str, body: str, buttons: list[dict]) -> dict:
        return record_outbound("buttons", recipient, {"body": body, "buttons": buttons})

    async def send_list(self, recipient: str, body: str, sections: list[dict]) -> dict:
        return record_outbound("list", recipient, {"body": body, "sections": sections})

    async def download_media(self, media_id: str) -> bytes:
        return MEDIA.get(media_id, b"")
