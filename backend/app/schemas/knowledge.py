from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import OrmModel


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    filename: str
    mime_type: str
    content_base64: str
    description: str | None = None
    category: str | None = None
    product: str | None = None
    version: str | None = None
    manufacturer: str | None = None
    valid_until: datetime | None = None
    approve: bool = False


class KnowledgeDocumentRead(OrmModel):
    id: UUID
    title: str
    description: str | None = None
    category: str | None = None
    product: str | None = None
    version: str | None = None
    manufacturer: str | None = None
    document_type: str
    status: str
    valid_until: datetime | None = None
    sha256: str
    size_bytes: int
    mime_type: str
    created_at: datetime
    updated_at: datetime


class KnowledgeChunkRead(OrmModel):
    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    keywords: list[str]


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=2)
    product: str | None = None
    version: str | None = None
    category: str | None = None


class KnowledgeApprovalRequest(BaseModel):
    approved: bool
    note: str | None = None


class KnowledgeSearchResult(BaseModel):
    document_id: str
    title: str
    excerpt: str
    score: float
    product: str | None = None
    version: str | None = None
    status: str
    reference: str
