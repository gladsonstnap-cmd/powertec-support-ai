from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    tenant_slug: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def validate_login_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email address")
        return normalized


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: UUID
    tenant_id: UUID


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20)
