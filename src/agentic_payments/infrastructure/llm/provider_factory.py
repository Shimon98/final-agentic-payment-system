"""Lazy provider-specific model construction for the public Agents SDK."""

from __future__ import annotations

from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.models.openai_responses import OpenAIResponsesModel
from openai import AsyncOpenAI

from agentic_payments.infrastructure.config import Settings
from agentic_payments.infrastructure.llm.exceptions import (
    LLMProviderConfigurationError,
    LLMUnavailableError,
)


class AgentsModelFactory:
    """Construct one SDK model shape without making a provider request."""

    GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

    def __init__(
        self,
        *,
        settings: Settings,
    ) -> None:
        if not isinstance(settings, Settings):
            raise TypeError("settings must be Settings")
        self._settings = settings

    def is_enabled(self) -> bool:
        """Return whether an external provider is explicitly enabled."""

        return self._settings.enable_llm_router and self._settings.llm_provider != "rule_based"

    def provider_name(self) -> str:
        """Return the configured non-secret provider name."""

        return self._settings.llm_provider

    def model_name(self) -> str:
        """Return the configured model or the disabled rule-based marker."""

        return self._settings.llm_model or "rule_based"

    def _configuration_error(self, missing: str) -> LLMProviderConfigurationError:
        return LLMProviderConfigurationError(
            "Language-model provider configuration is incomplete",
            context={"provider": self.provider_name(), "missing": missing},
        )

    def _required_model(self) -> str:
        model = self._settings.llm_model
        if model is None:
            raise self._configuration_error("model")
        return model

    def _required_api_key(self) -> str:
        secret = self._settings.llm_api_key
        if secret is None or not secret.get_secret_value().strip():
            raise self._configuration_error("api_key")
        return secret.get_secret_value()

    def _tracing_enabled(self) -> bool:
        return (
            self.is_enabled() and self.provider_name() == "openai" and self._settings.enable_tracing
        )

    def create_model(self) -> object:
        """Create a public SDK model object without sending a request."""

        if not self.is_enabled():
            raise LLMUnavailableError(
                "Language-model routing is disabled",
                context={"provider": self.provider_name()},
            )

        provider = self.provider_name()
        model_name = self._required_model()
        api_key = self._required_api_key()
        if provider == "openai":
            client = AsyncOpenAI(api_key=api_key)
            return OpenAIResponsesModel(model=model_name, openai_client=client)
        if provider == "gemini":
            base_url = self._settings.llm_base_url or self.GEMINI_OPENAI_BASE_URL
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            return OpenAIChatCompletionsModel(model=model_name, openai_client=client)
        if provider == "openai_compatible":
            compatible_base_url = self._settings.llm_base_url
            if compatible_base_url is None:
                raise self._configuration_error("base_url")
            client = AsyncOpenAI(api_key=api_key, base_url=compatible_base_url)
            return OpenAIChatCompletionsModel(model=model_name, openai_client=client)
        raise LLMProviderConfigurationError(
            "Unsupported language-model provider",
            context={"provider": provider},
        )
