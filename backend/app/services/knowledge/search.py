from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.support.schemas import KnowledgeSource
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeSearchLog, KnowledgeStatus
from app.services.knowledge.indexer import cosine_similarity, embedding_for, keywords_for


def search_knowledge(
    db: Session,
    tenant_id: UUID,
    query: str,
    *,
    product: str | None = None,
    version: str | None = None,
    category: str | None = None,
    limit: int = 5,
    approved_only: bool = True,
) -> list[KnowledgeSource]:
    query_terms = set(keywords_for(query))
    query_embedding = embedding_for(query)
    stmt = (
        select(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .where(KnowledgeChunk.tenant_id == tenant_id, KnowledgeDocument.tenant_id == tenant_id)
    )
    if approved_only:
        stmt = stmt.where(KnowledgeDocument.status == KnowledgeStatus.APPROVED.value)
        stmt = stmt.where((KnowledgeDocument.valid_until.is_(None)) | (KnowledgeDocument.valid_until >= datetime.now(UTC)))
    if product:
        stmt = stmt.where((KnowledgeDocument.product.is_(None)) | (KnowledgeDocument.product.ilike(f"%{product}%")) | (KnowledgeDocument.product == product))
    if version:
        stmt = stmt.where((KnowledgeDocument.version.is_(None)) | (KnowledgeDocument.version == version))
    if category:
        stmt = stmt.where(KnowledgeDocument.category == category)
    scored = []
    for chunk, document in db.execute(stmt).all():
        keyword_score = len(query_terms.intersection(set(chunk.keywords or []))) / max(len(query_terms), 1)
        vector_score = cosine_similarity(query_embedding, chunk.embedding or [])
        text_score = 0.2 if query.lower() in chunk.content.lower() else 0.0
        score = round(min(keyword_score + vector_score + text_score, 1.0), 4)
        if score <= 0:
            continue
        scored.append((score, chunk, document))
    scored.sort(key=lambda item: item[0], reverse=True)
    results = [
        KnowledgeSource(
            document_id=str(document.id),
            title=document.title,
            excerpt=chunk.content[:300],
            score=score,
            product=document.product,
            version=document.version,
            status=document.status,
            reference=f"KB-{str(document.id)[:8]}-{chunk.chunk_index}",
        )
        for score, chunk, document in scored[:limit]
    ]
    db.add(
        KnowledgeSearchLog(
            tenant_id=tenant_id,
            query=query[:2000],
            product=product,
            version=version,
            category=category,
            results_count=len(results),
            created_at=datetime.now(UTC),
        )
    )
    db.flush()
    return results
