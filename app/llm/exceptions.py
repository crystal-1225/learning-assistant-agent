class LLMError(Exception):
    """Base exception for LLM integration failures."""


class LLMConfigurationError(LLMError):
    """Raised when LLM mode is enabled but configuration is incomplete."""


class LLMRequestError(LLMError):
    """Raised when the provider request fails."""


class LLMInvalidResponseError(LLMError):
    """Raised when provider output cannot be parsed or validated."""

