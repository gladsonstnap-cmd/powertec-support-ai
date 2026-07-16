from pydantic import BaseModel

from app.agents.support.schemas import SupportAnalysis


class AIRequest(BaseModel):
    prompt: str
    context: dict


class AIResponse(BaseModel):
    analysis: SupportAnalysis
    provider: str
    model: str | None = None
