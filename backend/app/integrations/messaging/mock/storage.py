from datetime import UTC, datetime
from uuid import uuid4

OUTBOX: list[dict] = []
MEDIA: dict[str, bytes] = {}


def record_outbound(kind: str, recipient: str, payload: dict) -> dict:
    event = {
        "provider": "mock",
        "external_message_id": f"mock-out-{uuid4()}",
        "kind": kind,
        "recipient": recipient,
        "payload": payload,
        "created_at": datetime.now(UTC).isoformat(),
    }
    OUTBOX.append(event)
    return event
