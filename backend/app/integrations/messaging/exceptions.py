class MessagingError(Exception):
    """Base messaging error."""


class UnsupportedProviderError(MessagingError):
    """Raised when a provider is not enabled."""


class InvalidAttachmentError(MessagingError):
    """Raised when an attachment is unsafe or unsupported."""
