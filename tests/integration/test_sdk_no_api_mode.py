"""Default no-key mode imports and routes without SDK clients, tracing, or I/O."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import agentic_payments
from agentic_payments.agents import HybridRouterAgent, RouterAgent
from agentic_payments.application import BusinessMemory, RouterDecision
from agentic_payments.domain import Intent
from agentic_payments.infrastructure.config import Settings
from agentic_payments.infrastructure.llm import (
    AgentsModelFactory,
    LLMUnavailableError,
    OpenAIAgentsRuntime,
)


class NeverCalledGateway:
    async def route(
        self,
        *,
        user_input: str,
        correlation_id: str,
        memory: BusinessMemory,
    ) -> RouterDecision:
        raise AssertionError("LLM gateway must not be called")


def _data_snapshot() -> dict[str, bytes]:
    data = Path("data")
    return {str(path): path.read_bytes() for path in data.rglob("*") if path.is_file()}


def test_package_import_and_factory_construction_require_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_client(**_kwargs: Any) -> object:
        raise AssertionError("SDK client must not be constructed")

    monkeypatch.setattr(
        "agentic_payments.infrastructure.llm.provider_factory.AsyncOpenAI",
        fail_client,
    )
    settings = Settings(
        _env_file=None,
        llm_provider="rule_based",
        enable_llm_router=False,
        llm_api_key=None,
    )
    factory = AgentsModelFactory(settings=settings)
    runtime = OpenAIAgentsRuntime(model_factory=factory)
    assert agentic_payments.__name__ == "agentic_payments"
    assert not factory.is_enabled()
    with pytest.raises(LLMUnavailableError):
        runtime._router()


@pytest.mark.asyncio
async def test_default_hybrid_path_is_fully_deterministic_and_no_network() -> None:
    before = _data_snapshot()
    hybrid = HybridRouterAgent(
        deterministic_router=RouterAgent(),
        llm_gateway=NeverCalledGateway(),
        llm_enabled=False,
    )
    result = await hybrid.route("checkBalance user_id=USR-1")
    assert result.output.intent is Intent.CHECK_BALANCE
    assert result.metadata["mode"] == "canonical"
    assert _data_snapshot() == before


def test_default_settings_do_not_enable_tracing_or_external_provider() -> None:
    settings = Settings(_env_file=None)
    factory = AgentsModelFactory(settings=settings)
    assert settings.llm_provider == "rule_based"
    assert settings.enable_llm_router is False
    assert settings.enable_tracing is False
    assert not factory._tracing_enabled()
