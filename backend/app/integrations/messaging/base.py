from abc import ABC, abstractmethod


class MessagingProvider(ABC):
    @abstractmethod
    async def send_text(self, recipient: str, text: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def send_buttons(self, recipient: str, body: str, buttons: list[dict]) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def send_list(self, recipient: str, body: str, sections: list[dict]) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def download_media(self, media_id: str) -> bytes:
        raise NotImplementedError
