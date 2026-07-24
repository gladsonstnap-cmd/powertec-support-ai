from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.whatsapp import verify_webhook
from app.integrations.messaging.factory import get_messaging_provider
from app.integrations.messaging.mock.provider import MockMessagingProvider
from app.integrations.messaging.schemas import NormalizedWebhookMessage
from app.integrations.messaging.whatsapp.parser import normalize_meta_webhook
from app.integrations.messaging.whatsapp.provider import MetaWhatsAppProvider
from app.integrations.messaging.whatsapp.security import verify_meta_signature
from app.models.customer import Customer
from app.models.messaging import Contact, ConversationSession, MessagingEvent, MessagingMessage
from app.models.ticket import Ticket
from app.services.messaging import whatsapp_webhook as webhook_service


def meta_payload(message_type: str = "text", message_id: str = "wamid.1", text: str = "Todos os caixas pararam") -> dict:
    message = {"id": message_id, "from": "5594999990001", "timestamp": "1720000000", "type": message_type}
    if message_type == "text":
        message["text"] = {"body": text}
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"display_phone_number": "559400000000"},
                            "contacts": [{"wa_id": "5594999990001", "profile": {"name": "Maria Cliente"}}],
                            "messages": [message],
                        }
                    }
                ]
            }
        ],
    }


class FakeDb:
    def __init__(self, scalar_result=None):
        self.scalar_result = scalar_result
        self.objects = []

    def scalar(self, stmt):
        return self.scalar_result

    def add(self, obj):
        self.objects.append(obj)

    def flush(self):
        for obj in self.objects:
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()

    def commit(self):
        self.flush()

    def get(self, model, item_id):
        for obj in self.objects:
            if isinstance(obj, model) and getattr(obj, "id", None) == item_id:
                return obj
        return None


def test_meta_webhook_verification_valid(monkeypatch):
    monkeypatch.setattr("app.api.v1.endpoints.whatsapp.get_settings", lambda: SimpleNamespace(whatsapp_verify_token="verify-ok"))

    response = verify_webhook("subscribe", "verify-ok", "challenge-123")

    assert response.body == b"challenge-123"


def test_meta_webhook_verification_invalid(monkeypatch):
    monkeypatch.setattr("app.api.v1.endpoints.whatsapp.get_settings", lambda: SimpleNamespace(whatsapp_verify_token="verify-ok"))

    with pytest.raises(HTTPException) as exc:
        verify_webhook("subscribe", "wrong", "challenge-123")

    assert exc.value.status_code == 403


def test_normalizes_valid_text_message():
    messages = normalize_meta_webhook(meta_payload())

    assert len(messages) == 1
    assert messages[0].external_message_id == "wamid.1"
    assert messages[0].sender == "5594999990001"
    assert messages[0].contact_name == "Maria Cliente"
    assert messages[0].text == "Todos os caixas pararam"
    assert messages[0].supported is True


def test_payload_without_messages_is_safe():
    assert normalize_meta_webhook({"entry": [{"changes": [{"value": {"statuses": []}}]}]}) == []


def test_unsupported_message_type_is_normalized_without_crash():
    messages = normalize_meta_webhook(meta_payload(message_type="image"))

    assert messages[0].supported is False
    assert "unsupported" in messages[0].unsupported_reason


def test_provider_selection_preserves_mock(monkeypatch):
    monkeypatch.setattr("app.integrations.messaging.factory.get_settings", lambda: SimpleNamespace(whatsapp_provider="mock"))

    assert isinstance(get_messaging_provider(), MockMessagingProvider)


def test_provider_selection_meta(monkeypatch):
    monkeypatch.setattr("app.integrations.messaging.factory.get_settings", lambda: SimpleNamespace(whatsapp_provider="meta"))

    assert isinstance(get_messaging_provider(), MetaWhatsAppProvider)


@pytest.mark.asyncio
async def test_meta_provider_error_does_not_leak_credentials(monkeypatch):
    monkeypatch.setattr(
        "app.integrations.messaging.whatsapp.provider.get_settings",
        lambda: SimpleNamespace(
            whatsapp_access_token="secret-token",
            whatsapp_phone_number_id="123",
            whatsapp_api_version="v20.0",
            whatsapp_request_timeout_seconds=1,
        ),
    )

    class Response:
        status_code = 401

        def json(self):
            return {"error": {"message": "bad token"}}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("app.integrations.messaging.whatsapp.provider.httpx.AsyncClient", lambda timeout: Client())

    with pytest.raises(Exception) as exc:
        await MetaWhatsAppProvider().send_text("5594999990001", "Ola")

    assert "secret-token" not in str(exc.value)


def test_signature_validation_when_secret_is_configured():
    assert verify_meta_signature(b"{}", None, None) is True
    assert verify_meta_signature(b"{}", "sha256=invalid", "secret") is False


def test_process_text_message_creates_contact_session_ticket(monkeypatch):
    monkeypatch.setattr(webhook_service, "generate_protocol", lambda db, tenant_id: "PT-2026-000001")
    db = FakeDb()
    tenant_id = uuid4()

    result = webhook_service.process_normalized_messages(db, tenant_id, normalize_meta_webhook(meta_payload()))

    assert result["processed"] == 1
    assert result["duplicates"] == 0
    assert result["unsupported"] == 0
    assert len(result["response_candidates"]) == 1
    assert any(isinstance(obj, Contact) for obj in db.objects)
    assert any(isinstance(obj, ConversationSession) for obj in db.objects)
    assert any(isinstance(obj, Customer) for obj in db.objects)
    assert any(isinstance(obj, Ticket) for obj in db.objects)
    assert any(isinstance(obj, MessagingMessage) for obj in db.objects)


def test_duplicate_message_is_not_processed_twice():
    existing = MessagingMessage(
        tenant_id=uuid4(),
        external_message_id="wamid.1",
        provider="meta",
        direction="inbound",
        sender="a",
        recipient="b",
        message_type="text",
        payload={},
        status="received",
        processing_status="processed",
        created_at=webhook_service.datetime.now(webhook_service.UTC),
    )
    db = FakeDb(scalar_result=existing)

    result = webhook_service.process_normalized_messages(db, existing.tenant_id, normalize_meta_webhook(meta_payload()))

    assert result["duplicates"] == 1
    assert result["response_candidates"] == []
    assert not any(isinstance(obj, Ticket) for obj in db.objects)


def test_unsupported_message_records_event():
    db = FakeDb()
    tenant_id = uuid4()

    result = webhook_service.process_normalized_messages(db, tenant_id, normalize_meta_webhook(meta_payload(message_type="image")))

    assert result["unsupported"] == 1
    assert any(isinstance(obj, MessagingEvent) for obj in db.objects)


@pytest.mark.asyncio
async def test_new_message_generates_automatic_response_with_protocol(monkeypatch):
    monkeypatch.setattr(webhook_service, "generate_protocol", lambda db, tenant_id: "PT-2026-000777")
    db = FakeDb()
    tenant_id = uuid4()

    result = await webhook_service.process_messages_and_send_initial_response(db, tenant_id, normalize_meta_webhook(meta_payload()), MockMessagingProvider())

    outbound = [obj for obj in db.objects if isinstance(obj, MessagingMessage) and obj.direction == "outbound"]
    assert result["automatic_responses_sent"] == 1
    assert len(outbound) == 1
    assert "PT-2026-000777" in outbound[0].text_content
    assert "Olá, Maria Cliente" in outbound[0].text_content


@pytest.mark.asyncio
async def test_duplicate_message_does_not_generate_another_response():
    existing = MessagingMessage(
        tenant_id=uuid4(),
        external_message_id="wamid.1",
        provider="meta",
        direction="inbound",
        sender="a",
        recipient="b",
        message_type="text",
        payload={},
        status="received",
        processing_status="processed",
        created_at=webhook_service.datetime.now(webhook_service.UTC),
    )
    db = FakeDb(scalar_result=existing)

    result = await webhook_service.process_messages_and_send_initial_response(db, existing.tenant_id, normalize_meta_webhook(meta_payload()), MockMessagingProvider())

    assert result["duplicates"] == 1
    assert result["automatic_responses_sent"] == 0
    assert not any(isinstance(obj, MessagingMessage) and obj.direction == "outbound" for obj in db.objects)


@pytest.mark.asyncio
async def test_message_without_text_does_not_generate_response():
    db = FakeDb()
    tenant_id = uuid4()
    message = NormalizedWebhookMessage(
        provider="meta",
        external_message_id="wamid.empty",
        sender="5594999990001",
        recipient="559400000000",
        message_type="text",
        text="",
        supported=True,
    )

    result = await webhook_service.process_messages_and_send_initial_response(db, tenant_id, [message], MockMessagingProvider())

    assert result["processed"] == 0
    assert result["unsupported"] == 1
    assert result["automatic_responses_sent"] == 0


@pytest.mark.asyncio
async def test_provider_failure_records_automatic_response_failed(monkeypatch):
    monkeypatch.setattr(webhook_service, "generate_protocol", lambda db, tenant_id: "PT-2026-000888")
    db = FakeDb()
    tenant_id = uuid4()

    class FailingProvider:
        provider_name = "mock"

        async def send_text(self, recipient: str, text: str) -> dict:
            raise RuntimeError("secret-token should not leak")

    result = await webhook_service.process_messages_and_send_initial_response(db, tenant_id, normalize_meta_webhook(meta_payload()), FailingProvider())

    events = [obj for obj in db.objects if isinstance(obj, MessagingEvent) and obj.event_type == "automatic_response_failed"]
    assert result["processed"] == 1
    assert result["automatic_responses_failed"] == 1
    assert len(events) == 1
    assert "secret-token" not in events[0].payload["error"]


@pytest.mark.asyncio
async def test_inbound_and_outbound_are_linked_to_same_ticket_and_session(monkeypatch):
    monkeypatch.setattr(webhook_service, "generate_protocol", lambda db, tenant_id: "PT-2026-000999")
    db = FakeDb()
    tenant_id = uuid4()

    await webhook_service.process_messages_and_send_initial_response(db, tenant_id, normalize_meta_webhook(meta_payload()), MockMessagingProvider())

    inbound = next(obj for obj in db.objects if isinstance(obj, MessagingMessage) and obj.direction == "inbound")
    outbound = next(obj for obj in db.objects if isinstance(obj, MessagingMessage) and obj.direction == "outbound")
    assert outbound.ticket_id == inbound.ticket_id
    assert outbound.session_id == inbound.session_id
    assert outbound.contact_id == inbound.contact_id
    assert outbound.customer_id == inbound.customer_id
