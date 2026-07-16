from app.agents.support.schemas import SupportAnalysis
from app.core.config import get_settings
from app.integrations.ai.base import AIProvider
from app.integrations.ai.mock_provider import MockAIProvider
from app.integrations.ai.schemas import AIRequest, AIResponse


class OpenAIProvider(AIProvider):
    provider_name = "openai"

    async def analyze_support(self, request: AIRequest) -> AIResponse:
        settings = get_settings()
        if not settings.openai_api_key:
            return await MockAIProvider().analyze_support(request)
        # Prepared integration point: Responses API call should be added here with
        # structured output, timeout, context limits and secret masking.
        # The MVP deliberately falls back to deterministic mock behavior unless
        # the provider is fully configured and implemented.
        response = await MockAIProvider().analyze_support(request)
        return AIResponse(
            analysis=SupportAnalysis.model_validate(response.analysis),
            provider=self.provider_name,
            model=settings.openai_model or "fallback-mock",
        )
