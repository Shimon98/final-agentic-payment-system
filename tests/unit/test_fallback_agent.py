"""Safe fallback output, precondition, and dispatch tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentic_payments.agents import AgentContext, FallbackAgent
from agentic_payments.application import AgentResult, BusinessMemory, RouterDecision
from agentic_payments.domain import Intent

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
SUPPORTED = [
    "createUser",
    "checkBalance",
    "transferMoney",
    "requestPayment",
    "approvePayment",
    "rejectPayment",
    "showTransactions",
    "fraudCheck",
    "securityReview",
    "explainLastAction",
]


def _decision(
    *,
    confidence: float = 0.60,
    requires_clarification: bool = True,
    question: str | None = "מה חסר?",
) -> RouterDecision:
    return RouterDecision(
        intent=Intent.TRANSFER_MONEY,
        parameters={"sender_id": "SENDER"},
        confidence=confidence,
        requires_clarification=requires_clarification,
        clarification_question=question,
    )


@pytest.mark.asyncio
async def test_unknown_output_is_exact_and_does_not_echo_input() -> None:
    unknown = "full private unknown message 0501234567"
    result = await FallbackAgent().handle_unknown(unknown)
    assert isinstance(result, AgentResult)
    assert result.confidence == 1.0
    assert set(result.output) == {
        "reason",
        "message_he",
        "message_en",
        "clarification_question",
        "supported_intents",
    }
    assert result.output["reason"] == "unknown_intent"
    assert result.output["supported_intents"] == SUPPORTED
    assert unknown not in str(result.output)


@pytest.mark.asyncio
async def test_low_confidence_and_missing_parameter_outputs() -> None:
    decision = _decision()
    low = await FallbackAgent().handle_low_confidence(decision)
    missing = await FallbackAgent().request_missing_parameters(decision)

    assert low.output["reason"] == "low_confidence"
    assert missing.output["reason"] == "missing_parameters"
    assert low.output["clarification_question"] == "מה חסר?"
    assert missing.output["clarification_question"] == "מה חסר?"
    assert "receiver_id" not in str(missing.output)
    assert "amount" not in str(missing.output)


@pytest.mark.asyncio
async def test_low_confidence_precondition() -> None:
    with pytest.raises(ValueError):
        await FallbackAgent().handle_low_confidence(
            _decision(confidence=0.80, requires_clarification=False, question=None)
        )


@pytest.mark.asyncio
async def test_clarification_precondition() -> None:
    with pytest.raises(ValueError):
        await FallbackAgent().request_missing_parameters(
            _decision(
                confidence=1.0,
                requires_clarification=False,
                question=None,
            )
        )


@pytest.mark.asyncio
async def test_default_clarification_is_used_when_schema_was_constructed_without_one() -> None:
    decision = RouterDecision.model_construct(
        intent=Intent.TRANSFER_MONEY,
        parameters={},
        confidence=0.60,
        requires_clarification=True,
        clarification_question=None,
    )
    result = await FallbackAgent().request_missing_parameters(decision)
    assert result.output["clarification_question"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "decision", "reason"),
    [
        ("unknown", None, "unknown_intent"),
        ("low_confidence", _decision(), "low_confidence"),
        ("missing_parameters", _decision(), "missing_parameters"),
    ],
)
async def test_run_dispatch(
    mode: str,
    decision: RouterDecision | None,
    reason: str,
) -> None:
    result = await FallbackAgent().run(
        AgentContext(
            "fallback input",
            "COR-1",
            NOW,
            BusinessMemory(),
            router_decision=decision,
            payload={"fallback_mode": mode},
        )
    )
    assert result.output["reason"] == reason


@pytest.mark.asyncio
async def test_invalid_mode_and_missing_decision_are_rejected() -> None:
    agent = FallbackAgent()
    with pytest.raises(ValueError):
        await agent.run(
            AgentContext(
                "fallback",
                "COR-1",
                NOW,
                BusinessMemory(),
                payload={"fallback_mode": "invalid"},
            )
        )
    with pytest.raises(ValueError):
        await agent.run(
            AgentContext(
                "fallback",
                "COR-1",
                NOW,
                BusinessMemory(),
                payload={"fallback_mode": "low_confidence"},
            )
        )
