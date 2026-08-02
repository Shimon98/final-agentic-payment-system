"""Lazy provider-model factory tests with no network calls."""

from __future__ import annotations

from typing import Any

import pytest
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.models.openai_responses import OpenAIResponsesModel
from pydantic import SecretStr

from agentic_payments.infrastructure.config import Settings
from agentic_payments.infrastructure.llm.exceptions import (
    LLMProviderConfigurationError,
    LLMUnavailableError,
)
from agentic_payments.infrastructure.llm.provider_factory import AgentsModelFactory


def _settings(provider: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "llm_provider": provider,
        "enable_llm_router": provider != "rule_based",
        "llm_model": "test-model" if provider != "rule_based" else None,
        "llm_api_key": "test-secret-key" if provider != "rule_based" else None,
        "llm_base_url": (
            "https://compatible.example/v1/" if provider == "openai_compatible" else None
        ),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_rule_based_is_disabled_and_constructs_no_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_client(**_kwargs: Any) -> object:
        raise AssertionError("client construction is forbidden")

    monkeypatch.setattr(
        "agentic_payments.infrastructure.llm.provider_factory.AsyncOpenAI",
        fail_client,
    )
    factory = AgentsModelFactory(settings=_settings("rule_based"))
    assert not factory.is_enabled()
    assert factory.provider_name() == "rule_based"
    assert factory.model_name() == "rule_based"
    with pytest.raises(LLMUnavailableError):
        factory.create_model()


def test_openai_constructs_responses_model_without_request() -> None:
    factory = AgentsModelFactory(settings=_settings("openai"))
    model = factory.create_model()
    assert isinstance(model, OpenAIResponsesModel)


def test_gemini_constructs_chat_completions_model() -> None:
    factory = AgentsModelFactory(settings=_settings("gemini"))
    model = factory.create_model()
    assert isinstance(model, OpenAIChatCompletionsModel)


def test_custom_compatible_constructs_chat_completions_model() -> None:
    factory = AgentsModelFactory(settings=_settings("openai_compatible"))
    model = factory.create_model()
    assert isinstance(model, OpenAIChatCompletionsModel)


@pytest.mark.parametrize(
    ("provider", "expected_base_url"),
    [
        ("gemini", AgentsModelFactory.GEMINI_OPENAI_BASE_URL),
        ("openai_compatible", "https://compatible.example/v1/"),
    ],
)
def test_chat_compatible_base_url_is_passed_exactly(
    provider: str,
    expected_base_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    class FakeModel:
        def __init__(self, *, model: str, openai_client: object) -> None:
            captured["model"] = model
            captured["client"] = openai_client

    monkeypatch.setattr(
        "agentic_payments.infrastructure.llm.provider_factory.AsyncOpenAI",
        FakeClient,
    )
    monkeypatch.setattr(
        "agentic_payments.infrastructure.llm.provider_factory.OpenAIChatCompletionsModel",
        FakeModel,
    )
    model = AgentsModelFactory(settings=_settings(provider)).create_model()
    assert isinstance(model, FakeModel)
    assert captured["base_url"] == expected_base_url
    assert captured["api_key"] == "test-secret-key"
    assert captured["model"] == "test-model"


@pytest.mark.parametrize("missing", ["model", "api_key", "base_url"])
def test_missing_required_configuration_fails_safely(missing: str) -> None:
    values: dict[str, Any] = {
        "llm_provider": "openai_compatible",
        "enable_llm_router": True,
        "llm_model": "test-model",
        "llm_api_key": SecretStr("test-secret-key"),
        "llm_base_url": "https://compatible.example/v1/",
    }
    values[
        {"model": "llm_model", "api_key": "llm_api_key", "base_url": "llm_base_url"}[missing]
    ] = None
    invalid_settings = Settings.model_construct(**values)
    factory = AgentsModelFactory(settings=invalid_settings)
    with pytest.raises(LLMProviderConfigurationError) as captured:
        factory.create_model()
    assert "test-secret-key" not in repr(captured.value)
    assert captured.value.context["missing"] == missing


def test_disabled_network_provider_does_not_construct_client() -> None:
    factory = AgentsModelFactory(settings=_settings("openai", enable_llm_router=False))
    assert not factory.is_enabled()
    with pytest.raises(LLMUnavailableError):
        factory.create_model()


def test_factory_repr_and_configuration_error_do_not_expose_secret() -> None:
    settings = _settings("openai_compatible")
    factory = AgentsModelFactory(settings=settings)
    assert "test-secret-key" not in repr(factory)
    assert "test-secret-key" not in repr(settings)


def test_only_openai_provider_can_enable_tracing() -> None:
    openai = AgentsModelFactory(settings=_settings("openai", enable_tracing=True))
    gemini = AgentsModelFactory(settings=_settings("gemini", enable_tracing=True))
    assert openai._tracing_enabled()
    assert not gemini._tracing_enabled()
