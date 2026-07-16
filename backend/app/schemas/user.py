from uuid import UUID

from pydantic import EmailStr

from app.schemas.common import OrmModel


class UserRead(OrmModel):
    id: UUID
    tenant_id: UUID
    email: EmailStr
    full_name: str
    is_active: bool
