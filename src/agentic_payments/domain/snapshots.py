"""Immutable snapshots supplied to read-only specialist agents."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from agentic_payments.domain.entities import Transaction, _validate_money
from agentic_payments.domain.enums import TransactionStatus


@dataclass(frozen=True, slots=True)
class TransactionSnapshot:
    """Balances and recent activity associated with a completed transfer."""

    transaction: Transaction
    sender_balance_before: Decimal
    sender_balance_after: Decimal
    receiver_balance_before: Decimal
    receiver_balance_after: Decimal
    recent_sender_transactions: tuple[Transaction, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.transaction, Transaction):
            raise ValueError("transaction must be a Transaction")
        balances = {
            "sender_balance_before": self.sender_balance_before,
            "sender_balance_after": self.sender_balance_after,
            "receiver_balance_before": self.receiver_balance_before,
            "receiver_balance_after": self.receiver_balance_after,
        }
        for field_name, value in balances.items():
            balance = _validate_money(value, field_name)
            if balance < 0:
                raise ValueError(f"{field_name} cannot be negative")
        if self.transaction.status not in {
            TransactionStatus.COMPLETED,
            TransactionStatus.FLAGGED,
        }:
            raise ValueError("snapshot transaction must be completed or flagged")
        if self.sender_balance_after != self.sender_balance_before - self.transaction.amount:
            raise ValueError("sender balance equation is invalid")
        if self.receiver_balance_after != self.receiver_balance_before + self.transaction.amount:
            raise ValueError("receiver balance equation is invalid")
        if not isinstance(self.recent_sender_transactions, tuple):
            raise ValueError("recent_sender_transactions must be a tuple")
        for recent in self.recent_sender_transactions:
            if not isinstance(recent, Transaction):
                raise ValueError("recent_sender_transactions must contain Transaction values")
            if recent.sender_id != self.transaction.sender_id:
                raise ValueError("recent transaction sender does not match snapshot sender")
