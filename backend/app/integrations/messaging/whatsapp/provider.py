from app.integrations.messaging.base import MessagingProvider
from app.integrations.messaging.exceptions import UnsupportedProviderError


class WhatsAppMessagingProvider(MessagingProvider):
    async def send_text(self, recipient: str, text: str) -> dict:
        raise UnsupportedProviderError("WhatsApp provider is not active in the simulated stage.")

    async def send_buttons(self, recipient: str, body: str, buttons: list[dict]) -> dict:
        raise UnsupportedProviderError("WhatsApp provider is not active in the simulated stage.")

    async def send_list(self, recipient: str, body: str, sections: list[dict]) -> dict:
        raise UnsupportedProviderError("WhatsApp provider is not active in the simulated stage.")

    async def download_media(self, media_id: str) -> bytes:
        raise UnsupportedProviderError("WhatsApp provider is not active in the simulated stage.")
