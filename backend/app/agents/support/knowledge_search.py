from uuid import UUID

from sqlalchemy.orm import Session

from app.agents.support.schemas import KnowledgeSource
from app.services.knowledge.search import search_knowledge


def find_relevant_sources(
    db: Session,
    tenant_id: UUID,
    query: str,
    product: str | None = None,
    version: str | None = None,
) -> list[KnowledgeSource]:
    return search_knowledge(db, tenant_id, query, product=product, version=version, limit=5, approved_only=True)
