"""Deterministic transfer policy rules."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from agentic_payments.domain.entities import (
    Transaction,
    _validate_aware_datetime,
    _validate_money,
)
from agentic_payments.domain.enums import TransactionStatus
from agentic_payments.domain.exceptions import PolicyViolationError


@dataclass(frozen=True, slots=True)
class TransferPolicy:
    """Configured deterministic limits for transfer validation and risk context."""

    maximum_single_transfer: Decimal
    maximum_daily_transfer: Decimal
    suspicious_balance_ratio: Decimal
    rapid_transfer_window_minutes: int
    rapid_transfer_count: int

    def __post_init__(self) -> None:
        single = _validate_money(
            self.maximum_single_transfer,
            "maximum_single_transfer",
            positive=True,
        )
        daily = _validate_money(
            self.maximum_daily_transfer,
            "maximum_daily_transfer",
            positive=True,
        )
        if daily < single:
            raise ValueError("maximum_daily_transfer must be at least maximum_single_transfer")
        ratio = self.suspicious_balance_ratio
        if not isinstance(ratio, Decimal) or not ratio.is_finite() or not 0 < ratio <= 1:
            raise ValueError("suspicious_balance_ratio must be a finite Decimal in (0, 1]")
        if (
            isinstance(self.rapid_transfer_window_minutes, bool)
            or not isinstance(self.rapid_transfer_window_minutes, int)
            or self.rapid_transfer_window_minutes <= 0
        ):
            raise ValueError("rapid_transfer_window_minutes must be a positive integer")
        if (
            isinstance(self.rapid_transfer_count, bool)
            or not isinstance(self.rapid_transfer_count, int)
            or self.rapid_transfer_count <= 0
        ):
            raise ValueError("rapid_transfer_count must be a positive integer")

    def validate_amount(self, amount: Decimal) -> None:
        """Require a positive finite Decimal with at most two fractional digits."""

        _validate_money(amount, "amount", positive=True)

    def validate_single_transfer_limit(self, amount: Decimal) -> None:
        """Require an amount within the configured single-transfer limit."""

        self.validate_amount(amount)
        if amount > self.maximum_single_transfer:
            raise PolicyViolationError(
                "maximum_single_transfer",
                self.maximum_single_transfer,
                amount,
            )

    def validate_daily_limit(
        self,
        *,
        previous_transactions: Sequence[Transaction],
        amount: Decimal,
        now: datetime,
    ) -> None:
        """Require a transfer to fit within the rolling 24-hour limit."""

        self.validate_amount(amount)
        current_time = _validate_aware_datetime(now, "now")
        window_start = current_time - timedelta(hours=24)
        total = Decimal("0")
        for transaction in previous_transactions:
            if not isinstance(transaction, Transaction):
                raise ValueError("previous_transactions must contain Transaction values")
            if (
                transaction.status in {TransactionStatus.COMPLETED, TransactionStatus.FLAGGED}
                and window_start <= transaction.created_at <= current_time
            ):
                total += transaction.amount
        attempted = total + amount
        if attempted > self.maximum_daily_transfer:
            raise PolicyViolationError(
                "maximum_daily_transfer",
                self.maximum_daily_transfer,
                attempted,
            )

    def balance_ratio(self, *, balance_before: Decimal, amount: Decimal) -> Decimal:
        """Return the exact Decimal ratio of transfer amount to prior balance."""

        self.validate_amount(amount)
        balance = _validate_money(balance_before, "balance_before", positive=True)
        return amount / balance
