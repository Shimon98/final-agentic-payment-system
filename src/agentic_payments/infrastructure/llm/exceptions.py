"""Safe failures raised by the optional language-model infrastructure."""

from agentic_payments.infrastructure.exceptions import InfrastructureError


class LLMInfrastructureError(InfrastructureError):
    """Base class for safe language-model infrastructure failures."""


class LLMUnavailableError(LLMInfrastructureError):
    """The configured language-model service is disabled or unavailable."""


class LLMProviderConfigurationError(LLMInfrastructureError):
    """The selected language-model provider is not safely configured."""


class LLMStructuredOutputError(LLMInfrastructureError):
    """A provider result did not satisfy the required structured schema."""


class LLMHandoffError(LLMInfrastructureError):
    """A read-only SDK handoff was missing or reached the wrong specialist."""


class LLMGuardrailError(LLMInfrastructureError):
    """A read-only SDK input, tool, or output guardrail rejected content."""
