from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import OrmModel, TenantScopedCreate


class CustomerCreate(TenantScopedCreate):
    name: str = Field(min_length=2, max_length=160)
    document: str | None = Field(default=None, max_length=32)
    city: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    system_name: str | None = Field(default=None, max_length=120)


class CustomerRead(CustomerCreate, OrmModel):
    id: UUID
    is_active: bool


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    document: str | None = Field(default=None, max_length=32)
    city: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    system_name: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


class EstablishmentCreate(TenantScopedCreate):
    customer_id: UUID
    name: str = Field(min_length=2, max_length=160)
    internal_code: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=32)


class EstablishmentRead(EstablishmentCreate, OrmModel):
    id: UUID


class EstablishmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    internal_code: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
