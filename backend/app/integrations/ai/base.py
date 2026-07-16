from abc import ABC, abstractmethod

from app.integrations.ai.schemas import AIRequest, AIResponse


class AIProvider(ABC):
    provider_name: str

    @abstractmethod
    async def analyze_support(self, request: AIRequest) -> AIResponse:
        raise NotImplementedError
