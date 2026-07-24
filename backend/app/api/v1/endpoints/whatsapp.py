from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.integrations.messaging.whatsapp.parser import normalize_meta_webhook
from app.integrations.messaging.whatsapp.security import verify_meta_signature
from app.models.messaging import MessagingEvent
from app.services.messaging.whatsapp_webhook import default_webhook_tenant_id, process_normalized_messages

router = APIRouter()


def _configured_app_secret() -> str | None:
    secret = get_settings().whatsapp_app_secret
    if not secret or secret == "change-me":
        return None
    return secret


@router.get("/webhook")
def verify_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    settings = get_settings()
    if mode == "subscribe" and token == settings.whatsapp_verify_token and challenge is not None:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed")


@router.post("/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    if not verify_meta_signature(body, request.headers.get("x-hub-signature-256"), _configured_app_secret()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook signature")
    payload = await request.json()
    tenant_id = default_webhook_tenant_id(db)
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No active tenant configured")
    messages = normalize_meta_webhook(payload)
    if not messages:
        db.add(
            MessagingEvent(
                tenant_id=tenant_id,
                provider="meta",
                event_type="webhook_without_messages",
                payload={"object": payload.get("object"), "entry_count": len(payload.get("entry", []) or [])},
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
        return {"status": "ignored", "processed": 0, "duplicates": 0, "unsupported": 0}
    result = process_normalized_messages(db, tenant_id, messages)
    return {"status": "received", **result}
