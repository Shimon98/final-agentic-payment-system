"""Compatible-provider structured-output failures preserve deterministic routing."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from agents import Agent, Runner

from agentic_payments.agents import HybridRouterAgent, RouterAgent
from agentic_payments.application import ApplicationState
from agentic_payments.domain import Intent
from agentic_payments.infrastructure.config import Settings
from agentic_payments.infrastructure.llm import AgentsModelFactory, OpenAIAgentsRuntime


@pytest.mark.asyncio
async def test_compatible_structured_failure_falls_back_without_state_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class FreeTextResult:
        final_output = '{"intent":"transferMoney","amount":"10.00"}'
        last_agent = Agent(name="Payment Intent Router", model="test-model")
        new_items: list[object] = []

    async def fake_run(
        cls: type[Runner],
        starting_agent: Agent[Any],
        input: str,
        **kwargs: Any,
    ) -> object:
        nonlocal calls
        calls += 1
        return FreeTextResult()

    monkeypatch.setattr(Runner, "run", classmethod(fake_run))
    settings = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_model="test-model",
        llm_api_key="test-secret",
        llm_base_url="https://compatible.example/v1/",
        enable_llm_router=True,
    )
    runtime = OpenAIAgentsRuntime(model_factory=AgentsModelFactory(settings=settings))
    hybrid = HybridRouterAgent(
        deterministic_router=RouterAgent(),
        llm_gateway=runtime,
        llm_enabled=True,
    )
    state = ApplicationState()
    before = state.to_dict()
    result = await hybrid.route("transferMoney sender_id=USR-1 receiver_id=USR-2 amount=10.00")
    assert result.output.intent is Intent.TRANSFER_MONEY
    assert result.output.parameters["amount"] == Decimal("10.00")
    assert result.metadata == {
        "route_source": "deterministic_fallback",
        "llm_failure_type": "LLMStructuredOutputError",
    }
    assert state.to_dict() == before
    assert calls == 1
    assert isinstance(FreeTextResult.final_output, str)
