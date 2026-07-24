from app.core.config import get_settings
from app.integrations.messaging.base import MessagingProvider
from app.integrations.messaging.exceptions import UnsupportedProviderError
from app.integrations.messaging.mock.provider import MockMessagingProvider
from app.integrations.messaging.whatsapp.provider import MetaWhatsAppProvider


def get_messaging_provider() -> MessagingProvider:
    provider = get_settings().whatsapp_provider.lower()
    if provider == "mock":
        return MockMessagingProvider()
    if provider == "meta":
        return MetaWhatsAppProvider()
    raise UnsupportedProviderError(f"Messaging provider '{provider}' is not enabled.")
