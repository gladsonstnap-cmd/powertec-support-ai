class SupportAgentError(Exception):
    """Base support agent error."""


class InvalidAIResponseError(SupportAgentError):
    """Raised when an AI provider returns invalid structured data."""
