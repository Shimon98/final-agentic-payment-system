"""Deterministic read-only transfer-policy evaluation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from agentic_payments.agents import AgentContext, PolicyAgent
from agentic_payments.application import AgentResult, BusinessMemory, SecurityReview
from agentic_payments.domain import (
    RiskLevel,
    Transaction,
    TransactionStatus,
    TransferPolicy,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


def _policy() -> TransferPolicy:
    return TransferPolicy(
        maximum_single_transfer=Decimal("50.00"),
        maximum_daily_transfer=Decimal("100.00"),
        suspicious_balance_ratio=Decimal("0.70"),
        rapid_transfer_window_minutes=10,
        rapid_transfer_count=3,
    )


def _previous(transaction_id: str, amount: str) -> Transaction:
    return Transaction(
        transaction_id,
        "SENDER",
        "RECEIVER",
        Decimal(amount),
        NOW - timedelta(hours=1),
        TransactionStatus.COMPLETED,
        0,
        RiskLevel.LOW,
        (),
        None,
        f"COR-{transaction_id}",
        f"IDEM-{transaction_id}",
    )


@pytest.mark.asyncio
async def test_valid_transfer_policy_result_and_metadata() -> None:
    result = await PolicyAgent(transfer_policy=_policy()).evaluate_transfer(
        sender_id="SENDER",
        amount=Decimal("20.00"),
        balance_before=Decimal("100.00"),
        previous_transactions=(),
        now=NOW,
    )
    assert result.output == SecurityReview(
        approved=True,
        checks_performed=[
            "valid_amount",
            "single_transfer_limit",
            "daily_transfer_limit",
            "sufficient_balance",
        ],
        violations=[],
        recommendations=[],
    )
    assert result.metadata == {
        "sender_id": "SENDER",
        "amount": "20.00",
        "balance_before": "100.00",
        "previous_transaction_count": 0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("amount", "balance", "previous", "expected"),
    [
        (Decimal("-1.00"), Decimal("100.00"), (), ["invalid_amount"]),
        (Decimal("60.00"), Decimal("100.00"), (), ["policy_violation"]),
        (
            Decimal("30.00"),
            Decimal("100.00"),
            (_previous("TXN-1", "80.00"),),
            ["policy_violation"],
        ),
        (Decimal("30.00"), Decimal("20.00"), (), ["insufficient_funds"]),
    ],
)
async def test_each_policy_violation(
    amount: Decimal,
    balance: Decimal,
    previous: tuple[Transaction, ...],
    expected: list[str],
) -> None:
    review = (
        await PolicyAgent(transfer_policy=_policy()).evaluate_transfer(
            sender_id="SENDER",
            amount=amount,
            balance_before=balance,
            previous_transactions=previous,
            now=NOW,
        )
    ).output
    assert review.violations == expected
    assert review.approved is False
    assert len(review.recommendations) == len(expected)


@pytest.mark.asyncio
async def test_multiple_violations_are_unique_and_checks_remain_ordered() -> None:
    review = (
        await PolicyAgent(transfer_policy=_policy()).evaluate_transfer(
            sender_id="SENDER",
            amount=Decimal("60.00"),
            balance_before=Decimal("50.00"),
            previous_transactions=(_previous("TXN-1", "60.00"),),
            now=NOW,
        )
    ).output
    assert review.checks_performed == [
        "valid_amount",
        "single_transfer_limit",
        "daily_transfer_limit",
        "sufficient_balance",
    ]
    assert review.violations == ["policy_violation", "insufficient_funds"]


@pytest.mark.asyncio
async def test_previous_transactions_are_not_mutated() -> None:
    previous = [_previous("TXN-1", "10.00")]
    before = list(previous)
    await PolicyAgent(transfer_policy=_policy()).evaluate_transfer(
        sender_id="SENDER",
        amount=Decimal("20.00"),
        balance_before=Decimal("100.00"),
        previous_transactions=previous,
        now=NOW,
    )
    assert previous == before


@pytest.mark.asyncio
async def test_sender_and_time_validation() -> None:
    agent = PolicyAgent(transfer_policy=_policy())
    with pytest.raises(ValueError):
        await agent.evaluate_transfer(
            sender_id=" ",
            amount=Decimal("1.00"),
            balance_before=Decimal("10.00"),
            previous_transactions=(),
            now=NOW,
        )
    with pytest.raises(ValueError):
        await agent.evaluate_transfer(
            sender_id="SENDER",
            amount=Decimal("1.00"),
            balance_before=Decimal("10.00"),
            previous_transactions=(),
            now=datetime(2026, 8, 2),
        )


@pytest.mark.asyncio
async def test_run_requires_exact_transfer_facts_and_returns_agent_result() -> None:
    agent = PolicyAgent(transfer_policy=_policy())
    payload = {
        "sender_id": "SENDER",
        "amount": Decimal("20.00"),
        "balance_before": Decimal("100.00"),
        "previous_transactions": (),
        "now": NOW,
    }
    result = await agent.run(
        AgentContext("policy", "COR-1", NOW, BusinessMemory(), payload=payload)
    )
    assert isinstance(result, AgentResult)

    with pytest.raises(ValueError):
        await agent.run(AgentContext("policy", "COR-1", NOW, BusinessMemory()))
