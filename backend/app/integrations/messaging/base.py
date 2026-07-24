from abc import ABC, abstractmethod


class MessagingProvider(ABC):
    provider_name = "unknown"

    @abstractmethod
    async def send_text(self, recipient: str, text: str) -> dict:
        raise NotImplementedError

    async def normalize_webhook(self, payload: dict) -> list:
        return []

    async def mark_as_received(self, message_id: str) -> dict:
        return {"provider": self.provider_name, "external_message_id": message_id, "status": "received"}

    @abstractmethod
    async def send_buttons(self, recipient: str, body: str, buttons: list[dict]) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def send_list(self, recipient: str, body: str, sections: list[dict]) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def download_media(self, media_id: str) -> bytes:
        raise NotImplementedError
