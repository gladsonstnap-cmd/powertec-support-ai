import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeStatus
from app.services.knowledge.chunking import chunk_text
from app.services.knowledge.indexer import embedding_for, keywords_for
from app.services.knowledge.security import sanitize_document_text, validate_document_file


def extract_text(filename: str, content: bytes) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower()
    if suffix in {"txt", "md", "markdown", "csv", "log"}:
        return content.decode("utf-8", errors="replace")
    return content.decode("utf-8", errors="ignore") or f"Documento binario {filename} indexado sem extracao completa."


def create_document(
    db: Session,
    tenant_id: UUID,
    user_id: UUID | None,
    *,
    title: str,
    filename: str,
    mime_type: str,
    content: bytes,
    description: str | None = None,
    category: str | None = None,
    product: str | None = None,
    version: str | None = None,
    manufacturer: str | None = None,
    valid_until: datetime | None = None,
    approve: bool = False,
) -> KnowledgeDocument:
    document_type = validate_document_file(filename, mime_type, content)
    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.sha256 == digest))
    if existing is not None:
        raise ValueError("Duplicate knowledge document.")
    now = datetime.now(UTC)
    status = KnowledgeStatus.APPROVED.value if approve else KnowledgeStatus.PENDING_APPROVAL.value
    storage_key = f"knowledge/{tenant_id}/{digest}/{filename}"
    document = KnowledgeDocument(
        tenant_id=tenant_id,
        title=title,
        description=description,
        category=category,
        product=product,
        version=version,
        manufacturer=manufacturer,
        document_type=document_type,
        status=status,
        author_user_id=user_id,
        approver_user_id=user_id if approve else None,
        valid_until=valid_until,
        sha256=digest,
        size_bytes=len(content),
        mime_type=mime_type,
        storage_key=storage_key,
        created_at=now,
        updated_at=now,
    )
    db.add(document)
    db.flush()
    version_row = KnowledgeDocumentVersion(
        tenant_id=tenant_id,
        document_id=document.id,
        version_number=1,
        sha256=digest,
        storage_key=storage_key,
        created_at=now,
    )
    db.add(version_row)
    db.flush()
    text = sanitize_document_text(extract_text(filename, content))
    for index, chunk in enumerate(chunk_text(text)):
        db.add(
            KnowledgeChunk(
                tenant_id=tenant_id,
                document_id=document.id,
                version_id=version_row.id,
                chunk_index=index,
                content=chunk,
                content_hash=hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                keywords=keywords_for(chunk),
                embedding=embedding_for(chunk),
                created_at=now,
            )
        )
    db.commit()
    db.refresh(document)
    return document


def approve_document(db: Session, tenant_id: UUID, document_id: UUID, approver_id: UUID | None, approved: bool, note: str | None = None) -> KnowledgeDocument:
    document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id, KnowledgeDocument.tenant_id == tenant_id))
    if document is None:
        raise ValueError("Knowledge document not found.")
    document.status = KnowledgeStatus.APPROVED.value if approved else KnowledgeStatus.REJECTED.value
    document.approver_user_id = approver_id
    document.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(document)
    return document


def deactivate_document(db: Session, tenant_id: UUID, document_id: UUID) -> KnowledgeDocument:
    document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id, KnowledgeDocument.tenant_id == tenant_id))
    if document is None:
        raise ValueError("Knowledge document not found.")
    document.status = KnowledgeStatus.INACTIVE.value
    document.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(document)
    return document


def next_document_version(db: Session, document_id: UUID) -> int:
    value = db.scalar(select(func.max(KnowledgeDocumentVersion.version_number)).where(KnowledgeDocumentVersion.document_id == document_id))
    return int(value or 0) + 1
