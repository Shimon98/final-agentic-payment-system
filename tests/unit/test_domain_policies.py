"""Unit tests for deterministic transfer policy behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from agentic_payments.domain import (
    InvalidAmountError,
    PolicyViolationError,
    RiskLevel,
    Transaction,
    TransactionStatus,
    TransferPolicy,
)

NOW = datetime(2026, 3, 4, 15, tzinfo=UTC)


def policy(**overrides: object) -> TransferPolicy:
    values: dict[str, object] = {
        "maximum_single_transfer": Decimal("1000.00"),
        "maximum_daily_transfer": Decimal("2500.00"),
        "suspicious_balance_ratio": Decimal("0.70"),
        "rapid_transfer_window_minutes": 10,
        "rapid_transfer_count": 3,
    }
    values.update(overrides)
    return TransferPolicy(**values)  # type: ignore[arg-type]


def transaction(
    transaction_id: str,
    amount: str,
    created_at: datetime,
    status: TransactionStatus = TransactionStatus.COMPLETED,
) -> Transaction:
    return Transaction(
        transaction_id,
        "USR-001",
        "USR-002",
        Decimal(amount),
        created_at,
        status,
        0,
        RiskLevel.LOW,
        (),
        "simulated failure" if status is TransactionStatus.FAILED else None,
        "COR-001",
        f"IDEM-{transaction_id}",
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"maximum_single_transfer": Decimal("0")},
        {"maximum_single_transfer": Decimal("NaN")},
        {"maximum_single_transfer": Decimal("1.001")},
        {"maximum_daily_transfer": Decimal("999.99")},
        {"maximum_daily_transfer": Decimal("Infinity")},
        {"suspicious_balance_ratio": Decimal("0")},
        {"suspicious_balance_ratio": Decimal("1.01")},
        {"suspicious_balance_ratio": Decimal("NaN")},
        {"suspicious_balance_ratio": 0.5},
        {"rapid_transfer_window_minutes": 0},
        {"rapid_transfer_window_minutes": True},
        {"rapid_transfer_count": 0},
        {"rapid_transfer_count": True},
    ],
)
def test_domain_policy_constructor_validation(overrides: dict[str, object]) -> None:
    with pytest.raises((ValueError, InvalidAmountError)):
        policy(**overrides)


def test_domain_policy_accepts_valid_amount() -> None:
    policy().validate_amount(Decimal("10.25"))


@pytest.mark.parametrize(
    "amount",
    [0.1, Decimal("0"), Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity"), Decimal("1.001")],
)
def test_domain_policy_rejects_invalid_amount(amount: object) -> None:
    with pytest.raises(InvalidAmountError):
        policy().validate_amount(amount)  # type: ignore[arg-type]


def test_domain_policy_enforces_single_transfer_limit() -> None:
    policy().validate_single_transfer_limit(Decimal("1000.00"))
    with pytest.raises(PolicyViolationError) as raised:
        policy().validate_single_transfer_limit(Decimal("1000.01"))
    assert raised.value.policy_name == "maximum_single_transfer"
    assert raised.value.limit == Decimal("1000.00")
    assert raised.value.attempted == Decimal("1000.01")


def test_domain_policy_enforces_rolling_daily_limit() -> None:
    previous = [
        transaction("TXN-001", "1000.00", NOW - timedelta(hours=3)),
        transaction("TXN-002", "1000.00", NOW - timedelta(hours=2)),
    ]
    policy().validate_daily_limit(
        previous_transactions=previous,
        amount=Decimal("500.00"),
        now=NOW,
    )
    with pytest.raises(PolicyViolationError) as raised:
        policy().validate_daily_limit(
            previous_transactions=previous,
            amount=Decimal("500.01"),
            now=NOW,
        )
    assert raised.value.policy_name == "maximum_daily_transfer"
    assert raised.value.attempted == Decimal("2500.01")


def test_domain_policy_excludes_non_completed_and_out_of_window_transactions() -> None:
    previous = [
        transaction("TXN-FAILED", "900.00", NOW - timedelta(hours=1), TransactionStatus.FAILED),
        transaction("TXN-REJECTED", "900.00", NOW - timedelta(hours=1), TransactionStatus.REJECTED),
        transaction("TXN-PENDING", "900.00", NOW - timedelta(hours=1), TransactionStatus.PENDING),
        transaction("TXN-OLD", "900.00", NOW - timedelta(hours=24, microseconds=1)),
        transaction("TXN-FUTURE", "900.00", NOW + timedelta(seconds=1)),
    ]
    policy().validate_daily_limit(
        previous_transactions=previous,
        amount=Decimal("1000.00"),
        now=NOW,
    )


def test_domain_policy_includes_flagged_and_exact_24_hour_boundary() -> None:
    previous = [
        transaction("TXN-BOUNDARY", "1000.00", NOW - timedelta(hours=24)),
        transaction("TXN-FLAGGED", "1000.00", NOW, TransactionStatus.FLAGGED),
    ]
    with pytest.raises(PolicyViolationError):
        policy().validate_daily_limit(
            previous_transactions=previous,
            amount=Decimal("500.01"),
            now=NOW,
        )


def test_domain_policy_requires_aware_now() -> None:
    with pytest.raises(ValueError):
        policy().validate_daily_limit(
            previous_transactions=[],
            amount=Decimal("1.00"),
            now=datetime(2026, 3, 4, 15),
        )


def test_domain_policy_calculates_exact_decimal_balance_ratio() -> None:
    ratio = policy().balance_ratio(
        balance_before=Decimal("200.00"),
        amount=Decimal("50.00"),
    )
    assert ratio == Decimal("0.25")
    assert isinstance(ratio, Decimal)


@pytest.mark.parametrize(
    "balance",
    [0.0, Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), Decimal("1.001")],
)
def test_domain_policy_rejects_invalid_balance_ratio_denominator(balance: object) -> None:
    with pytest.raises(InvalidAmountError):
        policy().balance_ratio(
            balance_before=balance,  # type: ignore[arg-type]
            amount=Decimal("1.00"),
        )
