"""Deterministic ToolGuardrails contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from math import inf, nan

import pytest

from agentic_payments.application import (
    AgentResult,
    FraudAssessment,
    RequestContext,
    RouterDecision,
    SecurityReview,
    TransferMoneyCommand,
)
from agentic_payments.domain import Intent, RiskLevel
from agentic_payments.tools import ToolGuardrails

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
CONTEXT = RequestContext("COR", "IDEMP", NOW)
PARAMETERS = {"sender_id": "U1", "receiver_id": "U2", "amount": Decimal("1.00")}


def _decision(**changes: object) -> RouterDecision:
    values = {
        "intent": Intent.TRANSFER_MONEY,
        "parameters": PARAMETERS,
        "confidence": 1.0,
        "requires_clarification": False,
    }
    values.update(changes)
    return RouterDecision(**values)


def test_threshold_and_valid_before_execution() -> None:
    command = TransferMoneyCommand("U1", "U2", Decimal("1.00"), CONTEXT)
    ToolGuardrails().validate_before_execution(decision=_decision(), command=command)
    for invalid in (True, -0.1, 1.1):
        with pytest.raises((TypeError, ValueError)):
            ToolGuardrails(confidence_threshold=invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "decision",
    [
        RouterDecision(
            intent=Intent.UNKNOWN,
            parameters={},
            confidence=1.0,
        ),
        _decision(confidence=0.79),
        _decision(
            confidence=1.0,
            requires_clarification=True,
            clarification_question="More?",
        ),
        _decision(parameters={"sender_id": "U1", "receiver_id": "U2"}),
        _decision(parameters={**PARAMETERS, "extra": "x"}),
    ],
)
def test_invalid_route_contracts_are_rejected(decision: RouterDecision) -> None:
    command = TransferMoneyCommand("U1", "U2", Decimal("1.00"), CONTEXT)
    with pytest.raises(ValueError):
        ToolGuardrails().validate_before_execution(decision=decision, command=command)


def test_wrong_command_is_rejected() -> None:
    with pytest.raises(ValueError, match="TransferMoneyCommand"):
        ToolGuardrails().validate_before_execution(
            decision=_decision(),
            command=object(),
        )


def test_valid_schema_and_mapping_outputs_remain_unchanged() -> None:
    guardrails = ToolGuardrails()
    mapping = {"nested": ["ok", {"count": 1}], "enabled": True}
    result = AgentResult("Facade", mapping)
    guardrails.validate_after_execution(intent=Intent.TRANSFER_MONEY, result=result)
    assert result.output is mapping

    fraud = AgentResult(
        "Fraud",
        FraudAssessment(
            transaction_id="T1",
            risk_score=10,
            risk_level=RiskLevel.LOW,
            reasons=[],
            requires_security_review=False,
        ),
    )
    security = AgentResult(
        "Security",
        SecurityReview(
            approved=True,
            checks_performed=["state"],
            violations=[],
            recommendations=[],
        ),
    )
    guardrails.validate_after_execution(intent=Intent.FRAUD_CHECK, result=fraud)
    guardrails.validate_after_execution(intent=Intent.SECURITY_REVIEW, result=security)


@pytest.mark.parametrize(
    "output",
    [
        {"facts": {"confidence": 0.95}},
        {"facts": {"last_result": {"confidence": 1.0}}},
        {
            "facts": {
                "last_result": {
                    "metadata": {
                        "route_confidence": 0.8,
                        "confidence_threshold": 0.8,
                    }
                }
            }
        },
        {"facts": {"amount": "10.00", "balance": "20.00"}},
    ],
)
def test_explanation_allows_only_approved_finite_confidence_floats(
    output: dict[str, object],
) -> None:
    result = AgentResult("Explanation", output)
    ToolGuardrails().validate_after_execution(
        intent=Intent.EXPLAIN_LAST_ACTION,
        result=result,
    )
    assert result.output is output


@pytest.mark.parametrize(
    "output",
    [
        {"facts": {"amount": 1.0}},
        {"facts": {"balance": 1.0}},
        {"facts": {"sender_balance_before": 1.0}},
        {"facts": {"receiver_balance_after": 1.0}},
        {"facts": {"maximum_limit": 1.0}},
        {"facts": {"other": 1.0}},
        {"confidence": 1.0},
        {"facts": {"confidence": nan}},
        {"facts": {"confidence": inf}},
        {"facts": {"confidence": -inf}},
        {"facts": {"confidence": True}},
    ],
)
def test_explanation_rejects_money_other_nonfinite_and_bool_confidence(
    output: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        ToolGuardrails().validate_after_execution(
            intent=Intent.EXPLAIN_LAST_ACTION,
            result=AgentResult("Explanation", output),
        )


@pytest.mark.parametrize(
    "output",
    [
        {"facts": {"confidence": 0.95}},
        {"facts": {"last_result": {"confidence": 1.0}}},
        {"facts": {"last_result": {"metadata": {"route_confidence": 0.8}}}},
    ],
)
def test_non_explanation_intents_reject_the_same_confidence_float_paths(
    output: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        ToolGuardrails().validate_after_execution(
            intent=Intent.TRANSFER_MONEY,
            result=AgentResult("Facade", output),
        )


@pytest.mark.parametrize(
    ("intent", "output"),
    [
        (Intent.TRANSFER_MONEY, {}),
        (Intent.TRANSFER_MONEY, {"value": 1.2}),
        (Intent.TRANSFER_MONEY, {"value": Decimal("1.00")}),
        (Intent.FRAUD_CHECK, {"wrong": True}),
        (Intent.SECURITY_REVIEW, {"wrong": True}),
    ],
)
def test_invalid_post_execution_output_is_rejected(
    intent: Intent,
    output: object,
) -> None:
    with pytest.raises(ValueError):
        ToolGuardrails().validate_after_execution(
            intent=intent,
            result=AgentResult("Agent", output),
        )
