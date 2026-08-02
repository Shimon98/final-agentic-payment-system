"""Opt-in live structured router demonstration."""

from __future__ import annotations

import os

import pytest

from agentic_payments.application import BusinessMemory, RouterDecision
from agentic_payments.infrastructure.config import Settings
from agentic_payments.infrastructure.llm import AgentsModelFactory, OpenAIAgentsRuntime

_LIVE_ENABLED = os.getenv("RUN_LIVE_LLM_TESTS", "").lower() == "true"
_HAS_CREDENTIALS = bool(os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL"))

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(
        not (_LIVE_ENABLED and _HAS_CREDENTIALS),
        reason="live LLM tests require explicit opt-in and provider credentials",
    ),
]


@pytest.mark.asyncio
async def test_live_structured_router_decision() -> None:
    settings = Settings()
    runtime = OpenAIAgentsRuntime(model_factory=AgentsModelFactory(settings=settings))
    result = await runtime.route(
        user_input="Explain my last action",
        correlation_id="CORR-LIVE-ROUTER",
        memory=BusinessMemory(),
    )
    assert isinstance(result, RouterDecision)
