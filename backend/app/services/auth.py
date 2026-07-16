from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.tenant import Tenant
from app.models.user import RefreshToken, User
from app.security.passwords import verify_password
from app.security.tokens import create_access_token, create_refresh_token, decode_token


def hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def authenticate_user(db: Session, tenant_slug: str, email: str, password: str) -> User:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == tenant_slug, Tenant.is_active.is_(True)))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user = db.scalar(
        select(User).where(
            User.tenant_id == tenant.id,
            User.email == email.lower(),
            User.is_active.is_(True),
        )
    )
    if user is None or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return user


def issue_token_pair(db: Session, user: User) -> tuple[str, str]:
    settings = get_settings()
    access_token = create_access_token(user.id, user.tenant_id)
    refresh_token = create_refresh_token(user.id, user.tenant_id)
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    db.add(
        RefreshToken(
            user_id=user.id,
            tenant_id=user.tenant_id,
            token_hash=hash_token(refresh_token),
            expires_at=expires_at,
        )
    )
    db.commit()
    return access_token, refresh_token


def refresh_access_token(db: Session, refresh_token: str) -> tuple[User, str, str]:
    try:
        payload = decode_token(refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    token_record = db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(refresh_token),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(UTC),
        )
    )
    if token_record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked or expired")
    user = db.scalar(select(User).where(User.id == UUID(payload["sub"]), User.tenant_id == UUID(payload["tenant_id"])))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    token_record.revoked_at = datetime.now(UTC)
    access_token, new_refresh_token = issue_token_pair(db, user)
    return user, access_token, new_refresh_token
