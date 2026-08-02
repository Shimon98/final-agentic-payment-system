"""Unit tests for immutable transaction snapshots."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agentic_payments.domain import (
    PaymentDomainError,
    RiskLevel,
    Transaction,
    TransactionSnapshot,
    TransactionStatus,
)

NOW = datetime(2026, 4, 5, 10, tzinfo=UTC)


def transaction(
    *,
    transaction_id: str = "TXN-001",
    sender_id: str = "USR-001",
    receiver_id: str = "USR-002",
    status: TransactionStatus = TransactionStatus.COMPLETED,
) -> Transaction:
    return Transaction(
        transaction_id,
        sender_id,
        receiver_id,
        Decimal("25.00"),
        NOW,
        status,
        10,
        RiskLevel.LOW,
        (),
        None,
        "COR-001",
        f"IDEM-{transaction_id}",
    )


def snapshot(**overrides: object) -> TransactionSnapshot:
    values: dict[str, object] = {
        "transaction": transaction(),
        "sender_balance_before": Decimal("100.00"),
        "sender_balance_after": Decimal("75.00"),
        "receiver_balance_before": Decimal("20.00"),
        "receiver_balance_after": Decimal("45.00"),
        "recent_sender_transactions": (),
    }
    values.update(overrides)
    return TransactionSnapshot(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("status", [TransactionStatus.COMPLETED, TransactionStatus.FLAGGED])
def test_domain_snapshot_accepts_valid_completed_or_flagged_transaction(
    status: TransactionStatus,
) -> None:
    result = snapshot(transaction=transaction(status=status))
    assert result.transaction.status is status
    with pytest.raises(FrozenInstanceError):
        result.sender_balance_after = Decimal("0")  # type: ignore[misc]


def test_domain_snapshot_rejects_incorrect_sender_equation() -> None:
    with pytest.raises(ValueError, match="sender balance equation"):
        snapshot(sender_balance_after=Decimal("74.99"))


def test_domain_snapshot_rejects_incorrect_receiver_equation() -> None:
    with pytest.raises(ValueError, match="receiver balance equation"):
        snapshot(receiver_balance_after=Decimal("44.99"))


def test_domain_snapshot_rejects_mismatched_recent_sender() -> None:
    recent = transaction(
        transaction_id="TXN-RECENT",
        sender_id="USR-003",
        receiver_id="USR-004",
    )
    with pytest.raises(ValueError, match="sender does not match"):
        snapshot(recent_sender_transactions=(recent,))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sender_balance_before", Decimal("-0.01")),
        ("sender_balance_after", Decimal("NaN")),
        ("receiver_balance_before", 20.0),
        ("receiver_balance_after", Decimal("45.001")),
    ],
)
def test_domain_snapshot_rejects_invalid_balances(field: str, value: object) -> None:
    with pytest.raises((ValueError, PaymentDomainError)) as raised:
        snapshot(**{field: value})
    assert raised.value is not None


def test_domain_snapshot_rejects_pending_transaction() -> None:
    with pytest.raises(ValueError, match="completed or flagged"):
        snapshot(transaction=transaction(status=TransactionStatus.PENDING))


def test_domain_snapshot_validates_recent_sender_transactions() -> None:
    recent = transaction(transaction_id="TXN-RECENT")
    result = snapshot(recent_sender_transactions=(recent,))
    assert result.recent_sender_transactions == (recent,)
