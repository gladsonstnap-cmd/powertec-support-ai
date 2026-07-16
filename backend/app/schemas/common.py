from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TenantScopedCreate(BaseModel):
    tenant_id: UUID | None = None
