"""Exact ordered penalty and fallback tests for CriticAgent."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentic_payments.agents import AgentContext, CriticAgent
from agentic_payments.application import (
    AgentResult,
    BusinessMemory,
    CriticReview,
    FraudAssessment,
    SecurityReview,
)
from agentic_payments.domain import Intent, RiskLevel

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


def _fraud(level: RiskLevel = RiskLevel.LOW) -> FraudAssessment:
    return FraudAssessment(
        transaction_id="TXN-1",
        risk_score=80 if level is RiskLevel.HIGH else 10,
        risk_level=level,
        reasons=[],
        requires_security_review=level is RiskLevel.HIGH,
    )


def _security(*, approved: bool = True) -> SecurityReview:
    return SecurityReview(
        approved=approved,
        checks_performed=["check"],
        violations=[] if approved else ["violation"],
        recommendations=[] if approved else ["recommendation"],
    )


@pytest.mark.asyncio
async def test_valid_generic_result_is_approved() -> None:
    reviewed = await CriticAgent().review(
        AgentResult("AnyAgent", {"value": 1}, 1.0),
        Intent.CHECK_BALANCE,
    )
    assert reviewed.output == CriticReview(
        approved=True,
        quality_score=5,
        problems=[],
        requires_fallback=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_output", [None, "", "  ", {}, [], ()])
async def test_all_empty_output_forms_require_fallback(empty_output: object) -> None:
    review = (
        await CriticAgent().review(
            AgentResult("AnyAgent", empty_output),
            Intent.CHECK_BALANCE,
        )
    ).output
    assert review.problems == ["empty_output"]
    assert review.quality_score == 2
    assert review.approved is False
    assert review.requires_fallback is True


@pytest.mark.asyncio
async def test_low_confidence_penalty_alone_remains_approved() -> None:
    review = (
        await CriticAgent().review(
            AgentResult("AnyAgent", {"value": 1}, 0.49),
            Intent.CHECK_BALANCE,
        )
    ).output
    assert review == CriticReview(
        approved=True,
        quality_score=3,
        problems=["low_confidence"],
        requires_fallback=False,
    )


@pytest.mark.asyncio
async def test_expected_fraud_type_and_wrong_type() -> None:
    correct = (
        await CriticAgent().review(
            AgentResult("FraudDetectionAgent", _fraud()),
            Intent.FRAUD_CHECK,
        )
    ).output
    wrong = (
        await CriticAgent().review(
            AgentResult("AnyAgent", {"risk": "not structured"}),
            Intent.FRAUD_CHECK,
        )
    ).output

    assert correct.problems == []
    assert wrong.problems == ["unexpected_output_type"]
    assert wrong.quality_score == 3
    assert wrong.requires_fallback is True


@pytest.mark.asyncio
async def test_security_type_and_rejected_review() -> None:
    approved = (
        await CriticAgent().review(
            AgentResult("SecurityAgent", _security()),
            Intent.SECURITY_REVIEW,
        )
    ).output
    rejected = (
        await CriticAgent().review(
            AgentResult("SecurityAgent", _security(approved=False)),
            Intent.SECURITY_REVIEW,
        )
    ).output

    assert approved.quality_score == 5
    assert rejected == CriticReview(
        approved=True,
        quality_score=4,
        problems=["security_review_rejected"],
        requires_fallback=False,
    )


@pytest.mark.asyncio
async def test_high_fraud_risk_has_one_point_penalty() -> None:
    review = (
        await CriticAgent().review(
            AgentResult("FraudDetectionAgent", _fraud(RiskLevel.HIGH)),
            Intent.FRAUD_CHECK,
        )
    ).output
    assert review == CriticReview(
        approved=True,
        quality_score=4,
        problems=["high_fraud_risk"],
        requires_fallback=False,
    )


@pytest.mark.asyncio
async def test_penalties_clamp_score_and_preserve_problem_order() -> None:
    review = (
        await CriticAgent().review(
            AgentResult("AnyAgent", None, 0.1),
            Intent.FRAUD_CHECK,
        )
    ).output
    assert review.quality_score == 1
    assert review.problems == [
        "empty_output",
        "low_confidence",
        "unexpected_output_type",
    ]
    assert review.approved is False
    assert review.requires_fallback is True


@pytest.mark.asyncio
async def test_run_validates_payload_and_returns_agent_result() -> None:
    context = AgentContext(
        "critic",
        "COR-1",
        NOW,
        BusinessMemory(),
        payload={
            "result": AgentResult("AnyAgent", {"value": 1}),
            "expected_intent": Intent.CHECK_BALANCE,
        },
    )
    assert isinstance(await CriticAgent().run(context), AgentResult)

    for payload in (
        {},
        {"result": "wrong", "expected_intent": Intent.CHECK_BALANCE},
        {"result": AgentResult("A", {}), "expected_intent": "wrong"},
    ):
        with pytest.raises(TypeError):
            await CriticAgent().run(
                AgentContext("critic", "COR-1", NOW, BusinessMemory(), payload=payload)
            )
