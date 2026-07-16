from pydantic import BaseModel, Field, field_validator


class KnowledgeSource(BaseModel):
    document_id: str
    title: str
    excerpt: str
    score: float
    product: str | None = None
    version: str | None = None
    status: str
    reference: str


class SupportAnalysis(BaseModel):
    summary: str = ""
    category: str = ""
    subcategory: str = ""
    product: str = ""
    module: str = ""
    version: str = ""
    device: str = ""
    operating_system: str = ""
    error_message: str = ""
    impact: str = ""
    affected_users: int = 0
    store_stopped: bool = False
    fiscal_risk: bool = False
    data_loss_risk: bool = False
    priority: str = Field(pattern=r"^P[1-4]$")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_information: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    possible_causes: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    knowledge_sources: list[KnowledgeSource] = Field(default_factory=list)
    requires_human: bool = False
    requires_authorization: bool = False
    safety_notes: list[str] = Field(default_factory=list)
    triggered_rules: list[str] = Field(default_factory=list)

    @field_validator("recommended_actions")
    @classmethod
    def reject_unsafe_actions(cls, value: list[str]) -> list[str]:
        forbidden = ["excluir", "apagar", "sql", "formatar", "registro", "desativar antiv", "abrir porta", "trocar certificado"]
        for action in value:
            normalized = action.lower()
            if any(term in normalized for term in forbidden):
                raise ValueError("Unsafe recommended action")
        return value


class AgentContext(BaseModel):
    text: str
    product: str | None = None
    version: str | None = None
    previous_questions: list[str] = Field(default_factory=list)
    knowledge_sources: list[KnowledgeSource] = Field(default_factory=list)
    deterministic_priority: str
    triggered_rules: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    extracted: dict = Field(default_factory=dict)
