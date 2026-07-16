from uuid import UUID

from pydantic import Field

from app.schemas.common import OrmModel, TenantScopedCreate


class ProductCreate(TenantScopedCreate):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=255)


class ProductRead(ProductCreate, OrmModel):
    id: UUID


class ProductUpdate(OrmModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=255)


class ProductVersionCreate(TenantScopedCreate):
    product_id: UUID
    version: str = Field(min_length=1, max_length=40)
    is_supported: bool = True


class ProductVersionRead(ProductVersionCreate, OrmModel):
    id: UUID
