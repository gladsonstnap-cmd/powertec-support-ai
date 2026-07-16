from datetime import datetime
from uuid import UUID

from app.schemas.common import OrmModel


class TicketAnalysisRead(OrmModel):
    id: UUID
    ticket_id: UUID
    provider: str
    agent_version: str
    summary: str
    category: str | None = None
    subcategory: str | None = None
    product: str | None = None
    module: str | None = None
    version: str | None = None
    device: str | None = None
    operating_system: str | None = None
    error_message: str | None = None
    impact: str | None = None
    affected_users: int
    store_stopped: bool
    fiscal_risk: bool
    data_loss_risk: bool
    priority: str
    confidence: int
    missing_information: list[str]
    suggested_questions: list[str]
    possible_causes: list[str]
    recommended_actions: list[str]
    knowledge_sources: list[dict]
    triggered_rules: list[str]
    requires_human: bool
    requires_authorization: bool
    safety_notes: list[str]
    technician_feedback: dict
    created_at: datetime
    updated_at: datetime
