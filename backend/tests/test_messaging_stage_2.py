import pytest

from app.integrations.messaging.mock.provider import MockMessagingProvider
from app.services.messaging.attachments import validate_attachment
from app.services.messaging.classifier import classify_problem
from app.integrations.messaging.exceptions import InvalidAttachmentError


def test_classifier_marks_p1():
    result = classify_problem("Todos os caixas parados na loja")

    assert result.priority == "P1"
    assert "all_pos_down" in result.rules


def test_classifier_marks_p2():
    result = classify_problem("NFC-e nao emite desde cedo")

    assert result.priority == "P2"
    assert "nfce_not_issuing" in result.rules


def test_classifier_marks_normal_message_as_p4():
    result = classify_problem("Preciso tirar uma duvida de cadastro")

    assert result.priority == "P4"
    assert result.rules == []


def test_attachment_accepts_safe_text_file():
    metadata = validate_attachment("erro-demo.txt", "text/plain", b"log demo")

    assert metadata["safe_filename"].endswith(".txt")
    assert metadata["sha256"]


def test_attachment_rejects_malicious_filename():
    with pytest.raises(InvalidAttachmentError, match="Unsafe filename"):
        validate_attachment("../segredo.txt", "text/plain", b"x")


def test_attachment_rejects_invalid_mime():
    with pytest.raises(InvalidAttachmentError, match="Unsupported MIME type"):
        validate_attachment("run.exe", "application/x-msdownload", b"x")


@pytest.mark.asyncio
async def test_mock_provider_sends_text_buttons_and_list():
    provider = MockMessagingProvider()

    text = await provider.send_text("+5594999990001", "Ola")
    buttons = await provider.send_buttons("+5594999990001", "Escolha", [{"id": "sim", "title": "Sim"}])
    listing = await provider.send_list("+5594999990001", "Lista", [{"title": "Lojas", "rows": []}])

    assert text["provider"] == "mock"
    assert buttons["kind"] == "buttons"
    assert listing["kind"] == "list"
