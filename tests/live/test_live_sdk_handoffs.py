"""Opt-in live read-only handoff demonstrations."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from agentic_payments.domain import Intent
from agentic_payments.infrastructure.config import Settings
from agentic_payments.infrastructure.llm import (
    AgentsModelFactory,
    OpenAIAgentsRuntime,
    ReadOnlySpecialistOutput,
)

_LIVE_ENABLED = os.getenv("RUN_LIVE_LLM_TESTS", "").lower() == "true"
_HAS_CREDENTIALS = bool(os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL"))
_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(
        not (_LIVE_ENABLED and _HAS_CREDENTIALS),
        reason="live LLM tests require explicit opt-in and provider credentials",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "facts"),
    [
        (Intent.FRAUD_CHECK, {"risk_score": 10, "risk_level": "LOW"}),
        (Intent.SECURITY_REVIEW, {"checks_passed": True}),
        (Intent.EXPLAIN_LAST_ACTION, {"action": "checkBalance", "status": "completed"}),
    ],
)
async def test_live_read_only_specialist_handoff(
    intent: Intent,
    facts: dict[str, object],
) -> None:
    settings = Settings()
    runtime = OpenAIAgentsRuntime(model_factory=AgentsModelFactory(settings=settings))
    result = await runtime.run_specialist(
        intent=intent,
        user_input="Review the supplied read-only facts.",
        correlation_id="CORR-LIVE-HANDOFF",
        requested_at=_NOW,
        facts=facts,
    )
    assert isinstance(result.output, ReadOnlySpecialistOutput)
    assert result.metadata["handoff_occurred"] is True
