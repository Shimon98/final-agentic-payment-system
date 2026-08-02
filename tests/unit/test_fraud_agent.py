"""Exact deterministic scoring tests for FraudDetectionAgent."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agentic_payments.agents import AgentContext, FraudDetectionAgent
from agentic_payments.application import AgentResult, BusinessMemory, FraudAssessment
from agentic_payments.domain import (
    RiskLevel,
    Transaction,
    TransactionSnapshot,
    TransactionStatus,
    TransferPolicy,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


def _policy(
    *,
    maximum: str = "100.00",
    ratio: str = "0.70",
    rapid_count: int = 3,
) -> TransferPolicy:
    return TransferPolicy(
        maximum_single_transfer=Decimal(maximum),
        maximum_daily_transfer=Decimal("10000.00"),
        suspicious_balance_ratio=Decimal(ratio),
        rapid_transfer_window_minutes=10,
        rapid_transfer_count=rapid_count,
    )


def _transaction(
    transaction_id: str,
    amount: str,
    *,
    status: TransactionStatus = TransactionStatus.COMPLETED,
) -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        sender_id="SENDER",
        receiver_id="RECEIVER",
        amount=Decimal(amount),
        created_at=NOW,
        status=status,
        risk_score=0,
        risk_level=RiskLevel.LOW,
        risk_reasons=(),
        failure_reason=None,
        correlation_id=f"COR-{transaction_id}",
        idempotency_key=f"IDEM-{transaction_id}",
    )


def _snapshot(
    amount: str,
    *,
    sender_before: str = "1000.00",
    recent: tuple[Transaction, ...] = (),
) -> TransactionSnapshot:
    transaction = _transaction("TXN-CURRENT", amount)
    before = Decimal(sender_before)
    receiver_before = Decimal("20.00")
    return TransactionSnapshot(
        transaction=transaction,
        sender_balance_before=before,
        sender_balance_after=before - transaction.amount,
        receiver_balance_before=receiver_before,
        receiver_balance_after=receiver_before + transaction.amount,
        recent_sender_transactions=recent,
    )


@pytest.mark.asyncio
async def test_zero_risk_transfer() -> None:
    result = await FraudDetectionAgent(transfer_policy=_policy()).assess_transaction(
        _snapshot("10.00")
    )
    assert result.output == FraudAssessment(
        transaction_id="TXN-CURRENT",
        risk_score=0,
        risk_level=RiskLevel.LOW,
        reasons=[],
        requires_security_review=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("amount", "score", "reason"),
    [
        ("50.00", 10, "large_transfer_amount"),
        ("80.00", 25, "amount_near_single_transfer_limit"),
    ],
)
async def test_amount_thresholds(amount: str, score: int, reason: str) -> None:
    result = await FraudDetectionAgent(transfer_policy=_policy()).assess_transaction(
        _snapshot(amount)
    )
    assert result.output.risk_score == score
    assert result.output.reasons == [reason]


@pytest.mark.asyncio
async def test_exact_suspicious_ratio_boundary_uses_decimal() -> None:
    snapshot = _snapshot("70.00", sender_before="100.00")
    result = await FraudDetectionAgent(
        transfer_policy=_policy(maximum="1000.00")
    ).assess_transaction(snapshot)

    assert result.output.risk_score == 35
    assert result.output.risk_level is RiskLevel.MEDIUM
    assert result.output.requires_security_review is False
    assert result.metadata["calculated_balance_ratio"] == "0.7"
    assert not isinstance(result.metadata["calculated_balance_ratio"], float)


@pytest.mark.asyncio
async def test_rapid_activity_threshold_and_flagged_recent_activity() -> None:
    recent = (
        _transaction("TXN-1", "1.00"),
        _transaction("TXN-2", "1.00"),
        _transaction("TXN-3", "1.00", status=TransactionStatus.FLAGGED),
    )
    result = await FraudDetectionAgent(transfer_policy=_policy()).assess_transaction(
        _snapshot("10.00", recent=recent)
    )
    assert result.output.risk_score == 40
    assert result.output.reasons == [
        "rapid_transfer_activity",
        "recent_flagged_transaction",
    ]
    assert result.metadata["recent_transaction_count"] == 3


@pytest.mark.asyncio
async def test_combined_score_caps_at_100_and_reason_order_is_stable() -> None:
    recent = (
        _transaction("TXN-1", "1.00", status=TransactionStatus.FLAGGED),
        _transaction("TXN-2", "1.00"),
        _transaction("TXN-3", "1.00"),
    )
    result = await FraudDetectionAgent(transfer_policy=_policy()).assess_transaction(
        _snapshot("80.00", sender_before="100.00", recent=recent)
    )
    assert result.output.risk_score == 100
    assert result.output.risk_level is RiskLevel.HIGH
    assert result.output.requires_security_review is True
    assert result.output.reasons == [
        "amount_near_single_transfer_limit",
        "high_balance_percentage",
        "rapid_transfer_activity",
        "recent_flagged_transaction",
    ]


@pytest.mark.asyncio
async def test_low_medium_high_and_security_review_boundaries() -> None:
    agent = FraudDetectionAgent(transfer_policy=_policy())
    low = await agent.assess_transaction(_snapshot("80.00"))
    medium_35 = await FraudDetectionAgent(
        transfer_policy=_policy(maximum="1000.00")
    ).assess_transaction(_snapshot("70.00", sender_before="100.00"))
    recent = tuple(_transaction(f"TXN-{index}", "1.00") for index in range(3))
    medium_50 = await agent.assess_transaction(_snapshot("80.00", recent=recent))
    high_60 = await agent.assess_transaction(_snapshot("80.00", sender_before="100.00"))

    assert (low.output.risk_score, low.output.risk_level, low.output.requires_security_review) == (
        25,
        RiskLevel.LOW,
        False,
    )
    assert (
        medium_35.output.risk_score,
        medium_35.output.risk_level,
        medium_35.output.requires_security_review,
    ) == (35, RiskLevel.MEDIUM, False)
    assert (
        medium_50.output.risk_score,
        medium_50.output.risk_level,
        medium_50.output.requires_security_review,
    ) == (50, RiskLevel.MEDIUM, True)
    assert (
        high_60.output.risk_score,
        high_60.output.risk_level,
        high_60.output.requires_security_review,
    ) == (60, RiskLevel.HIGH, True)


@pytest.mark.asyncio
async def test_snapshot_remains_unchanged() -> None:
    snapshot = _snapshot("80.00")
    before = snapshot
    await FraudDetectionAgent(transfer_policy=_policy()).assess_transaction(snapshot)
    assert snapshot == before


@pytest.mark.asyncio
async def test_current_transaction_is_not_counted_as_recent_activity() -> None:
    current = _transaction(
        "TXN-CURRENT",
        "10.00",
        status=TransactionStatus.FLAGGED,
    )
    snapshot = _snapshot(
        "10.00",
        recent=(current, current, current),
    )
    result = await FraudDetectionAgent(transfer_policy=_policy()).assess_transaction(snapshot)

    assert result.output.risk_score == 0
    assert result.output.reasons == []
    assert result.metadata["recent_transaction_count"] == 0


@pytest.mark.asyncio
async def test_run_validates_snapshot_payload_and_returns_agent_result() -> None:
    agent = FraudDetectionAgent(transfer_policy=_policy())
    with pytest.raises(TypeError):
        await agent.run(AgentContext("fraud", "COR-1", NOW, BusinessMemory()))

    result = await agent.run(
        AgentContext(
            "fraud",
            "COR-1",
            NOW,
            BusinessMemory(),
            payload={"snapshot": _snapshot("10.00")},
        )
    )
    assert isinstance(result, AgentResult)
    assert isinstance(result.output, FraudAssessment)
