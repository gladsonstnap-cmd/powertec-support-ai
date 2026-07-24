import httpx

from app.core.config import get_settings
from app.integrations.messaging.base import MessagingProvider
from app.integrations.messaging.exceptions import ProviderDeliveryError, UnsupportedProviderError
from app.integrations.messaging.whatsapp.parser import normalize_meta_webhook


class MetaWhatsAppProvider(MessagingProvider):
    provider_name = "meta"

    async def send_text(self, recipient: str, text: str) -> dict:
        settings = get_settings()
        if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
            raise UnsupportedProviderError("Meta WhatsApp provider is not configured.")
        url = f"https://graph.facebook.com/{settings.whatsapp_api_version or 'v20.0'}/{settings.whatsapp_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=settings.whatsapp_request_timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderDeliveryError("Meta WhatsApp request failed.") from exc
        if response.status_code >= 400:
            raise ProviderDeliveryError(f"Meta WhatsApp returned HTTP {response.status_code}.")
        data = response.json()
        message_id = ((data.get("messages") or [{}])[0]).get("id")
        return {"provider": self.provider_name, "external_message_id": message_id or "", "status": "sent", "payload": {"status_code": response.status_code}}

    async def normalize_webhook(self, payload: dict) -> list:
        return normalize_meta_webhook(payload)

    async def send_buttons(self, recipient: str, body: str, buttons: list[dict]) -> dict:
        raise UnsupportedProviderError("Interactive messages are not enabled in this sprint.")

    async def send_list(self, recipient: str, body: str, sections: list[dict]) -> dict:
        raise UnsupportedProviderError("List messages are not enabled in this sprint.")

    async def download_media(self, media_id: str) -> bytes:
        raise UnsupportedProviderError("Media download is not enabled in this sprint.")


WhatsAppMessagingProvider = MetaWhatsAppProvider
