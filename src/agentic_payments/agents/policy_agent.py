"""Read-only deterministic transfer-policy evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from agentic_payments.agents.base import AgentContext, BaseAgent
from agentic_payments.application import AgentResult, SecurityReview
from agentic_payments.domain import (
    InvalidAmountError,
    PolicyViolationError,
    Transaction,
    TransferPolicy,
)

_CHECKS = [
    "valid_amount",
    "single_transfer_limit",
    "daily_transfer_limit",
    "sufficient_balance",
]

_RECOMMENDATIONS = {
    "invalid_amount": "Provide a positive Decimal amount with at most two decimal places.",
    "policy_violation": "Use an amount within the configured transfer limits.",
    "insufficient_funds": "Use an amount no greater than the available balance.",
}


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty stripped string")
    return value


class PolicyAgent(BaseAgent):
    """Evaluate policy facts without locks, state saves, or money movement."""

    def __init__(self, *, transfer_policy: TransferPolicy) -> None:
        if not isinstance(transfer_policy, TransferPolicy):
            raise TypeError("transfer_policy must be a TransferPolicy")
        self._transfer_policy = transfer_policy

    @property
    def name(self) -> str:
        """Return the stable policy-agent identity."""

        return "PolicyAgent"

    async def evaluate_transfer(
        self,
        *,
        sender_id: str,
        amount: Decimal,
        balance_before: Decimal,
        previous_transactions: Sequence[Transaction],
        now: datetime,
    ) -> AgentResult:
        """Run every approved transfer-policy check in deterministic order."""

        checked_sender = _text(sender_id, "sender_id")
        if not isinstance(amount, Decimal):
            raise TypeError("amount must be a Decimal")
        if not isinstance(balance_before, Decimal):
            raise TypeError("balance_before must be a Decimal")
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if isinstance(previous_transactions, (str, bytes)) or not isinstance(
            previous_transactions, Sequence
        ):
            raise TypeError("previous_transactions must be a Sequence")
        previous = tuple(previous_transactions)
        if not all(isinstance(transaction, Transaction) for transaction in previous):
            raise TypeError("previous_transactions must contain Transaction values")

        violations: list[str] = []
        try:
            self._transfer_policy.validate_amount(amount)
        except InvalidAmountError:
            violations.append("invalid_amount")
        try:
            self._transfer_policy.validate_single_transfer_limit(amount)
        except InvalidAmountError:
            violations.append("invalid_amount")
        except PolicyViolationError:
            violations.append("policy_violation")
        try:
            self._transfer_policy.validate_daily_limit(
                previous_transactions=previous,
                amount=amount,
                now=now,
            )
        except InvalidAmountError:
            violations.append("invalid_amount")
        except PolicyViolationError:
            violations.append("policy_violation")
        if not balance_before.is_finite() or not amount.is_finite() or balance_before < amount:
            violations.append("insufficient_funds")

        unique_violations = list(dict.fromkeys(violations))
        review = SecurityReview(
            approved=not unique_violations,
            checks_performed=list(_CHECKS),
            violations=unique_violations,
            recommendations=[_RECOMMENDATIONS[violation] for violation in unique_violations],
        )
        return AgentResult(
            self.name,
            review,
            1.0,
            {
                "sender_id": checked_sender,
                "amount": format(amount, "f"),
                "balance_before": format(balance_before, "f"),
                "previous_transaction_count": len(previous),
            },
        )

    async def run(self, context: AgentContext) -> AgentResult:
        """Evaluate the exact transfer facts supplied in payload."""

        if not isinstance(context, AgentContext):
            raise TypeError("context must be AgentContext")
        required = {
            "sender_id",
            "amount",
            "balance_before",
            "previous_transactions",
            "now",
        }
        if not required.issubset(context.payload):
            raise ValueError("policy payload is missing required fields")
        sender_id = context.payload["sender_id"]
        amount = context.payload["amount"]
        balance_before = context.payload["balance_before"]
        previous_transactions = context.payload["previous_transactions"]
        now = context.payload["now"]
        if not isinstance(sender_id, str):
            raise TypeError("sender_id payload must be a string")
        if not isinstance(amount, Decimal):
            raise TypeError("amount payload must be Decimal")
        if not isinstance(balance_before, Decimal):
            raise TypeError("balance_before payload must be Decimal")
        if isinstance(previous_transactions, (str, bytes)) or not isinstance(
            previous_transactions, Sequence
        ):
            raise TypeError("previous_transactions payload must be a Sequence")
        if not isinstance(now, datetime):
            raise TypeError("now payload must be datetime")
        return await self.evaluate_transfer(
            sender_id=sender_id,
            amount=amount,
            balance_before=balance_before,
            previous_transactions=previous_transactions,
            now=now,
        )
