"""Defensive SDK read-only context tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

import pytest

from agentic_payments.application import ApplicationState
from agentic_payments.domain import Intent, RiskLevel
from agentic_payments.infrastructure.llm.context import SDKReadOnlyContext

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "intent",
    [Intent.FRAUD_CHECK, Intent.SECURITY_REVIEW, Intent.EXPLAIN_LAST_ACTION],
)
def test_every_approved_read_only_intent(intent: Intent) -> None:
    context = SDKReadOnlyContext(intent, "CORR-1", NOW, {"status": "ok"})
    assert context.allowed_intent is intent


@pytest.mark.parametrize(
    "intent",
    [
        Intent.CREATE_USER,
        Intent.TRANSFER_MONEY,
        Intent.REQUEST_PAYMENT,
        Intent.APPROVE_PAYMENT,
        Intent.REJECT_PAYMENT,
        Intent.CHECK_BALANCE,
        Intent.UNKNOWN,
    ],
)
def test_non_specialist_intents_are_rejected(intent: Intent) -> None:
    with pytest.raises(ValueError):
        SDKReadOnlyContext(intent, "CORR-1", NOW, {})


def test_facts_are_defensively_recursively_immutable() -> None:
    source = {"nested": {"items": ["a", "b"]}}
    context = SDKReadOnlyContext(Intent.FRAUD_CHECK, "CORR-1", NOW, source)
    source["nested"]["items"].append("changed")
    assert isinstance(context.facts, MappingProxyType)
    assert context.facts["nested"]["items"] == ("a", "b")
    with pytest.raises(TypeError):
        context.facts["new"] = "value"  # type: ignore[index]


def test_decimal_datetime_and_enum_are_converted() -> None:
    context = SDKReadOnlyContext(
        Intent.FRAUD_CHECK,
        "CORR-1",
        NOW,
        {
            "amount": Decimal("12.30"),
            "occurred_at": NOW,
            "risk_level": RiskLevel.LOW,
        },
    )
    assert context.facts == {
        "amount": "12.30",
        "occurred_at": NOW.isoformat(),
        "risk_level": "LOW",
    }


def test_float_money_is_rejected_but_non_money_metric_is_allowed() -> None:
    with pytest.raises(ValueError, match="monetary float"):
        SDKReadOnlyContext(Intent.FRAUD_CHECK, "CORR-1", NOW, {"amount": 1.25})
    context = SDKReadOnlyContext(
        Intent.FRAUD_CHECK,
        "CORR-1",
        NOW,
        {"confidence": 0.8},
    )
    assert context.facts["confidence"] == 0.8


@pytest.mark.parametrize(
    "key",
    ["api_key", "Authorization", "client_secret", "password_hash", "token", "raw_prompt"],
)
def test_secret_like_keys_are_rejected(key: str) -> None:
    with pytest.raises(ValueError, match="prohibited key"):
        SDKReadOnlyContext(Intent.SECURITY_REVIEW, "CORR-1", NOW, {key: "hidden"})


def test_complete_phone_number_is_rejected() -> None:
    with pytest.raises(ValueError, match="phone number"):
        SDKReadOnlyContext(
            Intent.EXPLAIN_LAST_ACTION,
            "CORR-1",
            NOW,
            {"contact": "050-123-4567"},
        )


@pytest.mark.parametrize("facts", [{"state": ApplicationState()}, {"service": object()}])
def test_state_service_repository_or_unknown_object_is_rejected(
    facts: dict[str, object],
) -> None:
    with pytest.raises(TypeError, match="unsupported"):
        SDKReadOnlyContext(Intent.SECURITY_REVIEW, "CORR-1", NOW, facts)


def test_invalid_correlation_and_naive_time_are_rejected() -> None:
    with pytest.raises(ValueError, match="correlation"):
        SDKReadOnlyContext(Intent.FRAUD_CHECK, " CORR-1 ", NOW, {})
    with pytest.raises(ValueError, match="timezone-aware"):
        SDKReadOnlyContext(
            Intent.FRAUD_CHECK,
            "CORR-1",
            datetime(2026, 8, 2, 12, 0),
            {},
        )
