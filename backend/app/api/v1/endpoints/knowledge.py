import base64
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeApprovalRequest,
    KnowledgeChunkRead,
    KnowledgeDocumentCreate,
    KnowledgeDocumentRead,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)
from app.security.dependencies import get_current_user
from app.services.knowledge.documents import approve_document, create_document, deactivate_document
from app.services.knowledge.search import search_knowledge

router = APIRouter()


@router.get("/documents", response_model=list[KnowledgeDocumentRead])
def list_documents(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return list(db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.tenant_id == current_user.tenant_id).order_by(KnowledgeDocument.updated_at.desc())))


@router.post("/documents", response_model=KnowledgeDocumentRead, status_code=201)
def upload_document(payload: KnowledgeDocumentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
        return create_document(
            db,
            current_user.tenant_id,
            current_user.id,
            title=payload.title,
            filename=payload.filename,
            mime_type=payload.mime_type,
            content=content,
            description=payload.description,
            category=payload.category,
            product=payload.product,
            version=payload.version,
            manufacturer=payload.manufacturer,
            valid_until=payload.valid_until,
            approve=payload.approve,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/documents/{document_id}/chunks", response_model=list[KnowledgeChunkRead])
def list_chunks(document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return list(
        db.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.tenant_id == current_user.tenant_id, KnowledgeChunk.document_id == document_id)
            .order_by(KnowledgeChunk.chunk_index)
        )
    )


@router.post("/documents/{document_id}/approval", response_model=KnowledgeDocumentRead)
def review_document(document_id: UUID, payload: KnowledgeApprovalRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return approve_document(db, current_user.tenant_id, document_id, current_user.id, payload.approved, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/documents/{document_id}/deactivate", response_model=KnowledgeDocumentRead)
def deactivate(document_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return deactivate_document(db, current_user.tenant_id, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/search", response_model=list[KnowledgeSearchResult])
def search(payload: KnowledgeSearchRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    results = search_knowledge(
        db,
        current_user.tenant_id,
        payload.query,
        product=payload.product,
        version=payload.version,
        category=payload.category,
    )
    db.commit()
    return results
