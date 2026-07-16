from app.core.config import get_settings
from app.integrations.ai.base import AIProvider
from app.integrations.ai.mock_provider import MockAIProvider
from app.integrations.ai.openai_provider import OpenAIProvider


def get_ai_provider() -> AIProvider:
    provider = get_settings().ai_provider.lower()
    if provider == "mock":
        return MockAIProvider()
    if provider == "openai":
        return OpenAIProvider()
    return MockAIProvider()
