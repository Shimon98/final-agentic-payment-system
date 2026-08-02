"""Tests for shared results and Pydantic application schemas."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agentic_payments.application import (
    AgentResult,
    CriticReview,
    FraudAssessment,
    ReflectionAdvice,
    RouterDecision,
    SecurityReview,
)
from agentic_payments.domain import Intent, RiskLevel


def test_application_result_valid_boundaries_and_metadata_copy() -> None:
    metadata = {"trace": "one"}
    low = AgentResult("router", {"ok": True}, 0, metadata)
    high = AgentResult("router", None, 1)
    metadata["trace"] = "changed"
    assert (low.confidence, high.confidence) == (0.0, 1.0)
    assert low.metadata == {"trace": "one"}


@pytest.mark.parametrize("confidence", [True, "0.5", -0.1, 1.1])
def test_application_result_rejects_invalid_confidence(confidence: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        AgentResult("agent", None, confidence)


@pytest.mark.parametrize("intent", list(Intent))
def test_application_schema_router_accepts_every_intent(intent: Intent) -> None:
    decision = RouterDecision(intent=intent, parameters={}, confidence=0.8)
    assert decision.intent is intent


def test_application_schema_router_copies_parameters_and_forbids_extra() -> None:
    parameters = {"user_id": "USR-001"}
    decision = RouterDecision(intent=Intent.CHECK_BALANCE, parameters=parameters, confidence=1)
    parameters["user_id"] = "changed"
    assert decision.parameters == {"user_id": "USR-001"}
    with pytest.raises(ValidationError):
        RouterDecision(intent=Intent.UNKNOWN, parameters={}, confidence=1, extra=True)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "values",
    [
        {"requires_clarification": True, "clarification_question": None},
        {"requires_clarification": True, "clarification_question": " "},
        {"requires_clarification": False, "clarification_question": "Question?"},
    ],
)
def test_application_schema_router_clarification_consistency(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RouterDecision(intent=Intent.UNKNOWN, parameters={}, confidence=0.5, **values)


def test_application_schema_unknown_rejects_executable_parameters() -> None:
    with pytest.raises(ValidationError):
        RouterDecision(intent=Intent.UNKNOWN, parameters={"amount": "10.00"}, confidence=0.4)


@pytest.mark.parametrize("score", [0, 100])
def test_application_schema_fraud_score_boundaries(score: int) -> None:
    assessment = FraudAssessment(
        transaction_id="TXN-001",
        risk_score=score,
        risk_level=RiskLevel.MEDIUM,
        reasons=[],
        requires_security_review=False,
    )
    assert assessment.risk_score == score


@pytest.mark.parametrize(
    ("level", "review"),
    [(RiskLevel.HIGH, False), (RiskLevel.LOW, True)],
)
def test_application_schema_fraud_review_invariants(level: RiskLevel, review: bool) -> None:
    with pytest.raises(ValidationError):
        FraudAssessment(
            transaction_id="TXN-001",
            risk_score=50,
            risk_level=level,
            reasons=["reason"],
            requires_security_review=review,
        )


@pytest.mark.parametrize("reasons", [[""], [" reason"], "reason"])
def test_application_schema_fraud_rejects_invalid_reasons(reasons: Any) -> None:
    with pytest.raises((ValidationError, TypeError)):
        FraudAssessment(
            transaction_id="TXN-001",
            risk_score=50,
            risk_level=RiskLevel.MEDIUM,
            reasons=reasons,
            requires_security_review=False,
        )


def test_application_schema_security_review_invariants() -> None:
    SecurityReview(approved=True, checks_performed=["balances"], violations=[], recommendations=[])
    SecurityReview(
        approved=False,
        checks_performed=["balances"],
        violations=["negative balance"],
        recommendations=["repair state"],
    )
    with pytest.raises(ValidationError):
        SecurityReview(
            approved=True,
            checks_performed=[],
            violations=["violation"],
            recommendations=[],
        )
    with pytest.raises(ValidationError):
        SecurityReview(approved=False, checks_performed=[], violations=[], recommendations=[])


@pytest.mark.parametrize("score", [1, 5])
def test_application_schema_critic_score_boundaries(score: int) -> None:
    CriticReview(
        approved=score >= 4,
        quality_score=score,
        problems=[] if score >= 4 else ["problem"],
        requires_fallback=score <= 2,
    )


@pytest.mark.parametrize(
    "values",
    [
        {"approved": False, "quality_score": 3, "problems": [], "requires_fallback": False},
        {"approved": True, "quality_score": 4, "problems": [], "requires_fallback": True},
        {"approved": False, "quality_score": 2, "problems": ["bad"], "requires_fallback": False},
    ],
)
def test_application_schema_critic_fallback_invariants(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CriticReview(**values)


def test_application_schema_reflection_validation_and_round_trip() -> None:
    advice = ReflectionAdvice(
        error_code="insufficient_funds",
        user_message="Choose a smaller amount.",
        recovery_steps=["Check the balance"],
        suggested_parameters={"amount": "10.00"},
    )
    assert ReflectionAdvice.model_validate_json(advice.model_dump_json()) == advice
    with pytest.raises(ValidationError):
        ReflectionAdvice(
            error_code="Not-Snake",
            user_message="message",
            recovery_steps=[],
            suggested_parameters={},
        )


def test_application_schemas_are_frozen() -> None:
    decision = RouterDecision(intent=Intent.UNKNOWN, parameters={}, confidence=1)
    with pytest.raises(ValidationError):
        decision.confidence = 0.5  # type: ignore[misc]
