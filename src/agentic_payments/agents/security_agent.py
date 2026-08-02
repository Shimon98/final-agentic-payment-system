"""Read-only transaction and aggregate invariant security reviews."""

from __future__ import annotations

from decimal import Decimal

from agentic_payments.agents.base import AgentContext, BaseAgent
from agentic_payments.application import AgentResult, ApplicationState, SecurityReview
from agentic_payments.domain import (
    StateInvariantError,
    TransactionSnapshot,
    TransactionStatus,
)

_TRANSACTION_CHECKS = [
    "positive_amount",
    "different_participants",
    "sender_balance_equation",
    "receiver_balance_equation",
    "non_negative_balances",
    "supported_status",
]

_RECOMMENDATIONS = {
    "invalid_amount": "Use a positive monetary amount.",
    "self_transfer": "Use different sender and receiver identifiers.",
    "sender_balance_mismatch": "Reconcile the sender balance equation.",
    "receiver_balance_mismatch": "Reconcile the receiver balance equation.",
    "negative_balance": "Restore all balances to non-negative values.",
    "unsupported_transaction_status": "Use a completed or flagged transaction snapshot.",
    "state_invariant_violation": "Review application-state references and invariants safely.",
}


def _unique_recommendations(violations: list[str]) -> list[str]:
    return [_RECOMMENDATIONS[violation] for violation in dict.fromkeys(violations)]


class SecurityAgent(BaseAgent):
    """Review immutable facts without performing or reversing any transaction."""

    @property
    def name(self) -> str:
        """Return the stable security-agent identity."""

        return "SecurityAgent"

    async def review_transaction(self, snapshot: TransactionSnapshot) -> AgentResult:
        """Review exact transaction arithmetic and supported immutable facts."""

        if not isinstance(snapshot, TransactionSnapshot):
            raise TypeError("snapshot must be a TransactionSnapshot")
        transaction = snapshot.transaction
        violations: list[str] = []

        if not isinstance(transaction.amount, Decimal) or transaction.amount <= 0:
            violations.append("invalid_amount")
        if transaction.sender_id == transaction.receiver_id:
            violations.append("self_transfer")
        if snapshot.sender_balance_after != snapshot.sender_balance_before - transaction.amount:
            violations.append("sender_balance_mismatch")
        if snapshot.receiver_balance_after != snapshot.receiver_balance_before + transaction.amount:
            violations.append("receiver_balance_mismatch")
        balances = (
            snapshot.sender_balance_before,
            snapshot.sender_balance_after,
            snapshot.receiver_balance_before,
            snapshot.receiver_balance_after,
        )
        if any(balance < 0 for balance in balances):
            violations.append("negative_balance")
        if transaction.status not in {
            TransactionStatus.COMPLETED,
            TransactionStatus.FLAGGED,
        }:
            violations.append("unsupported_transaction_status")

        unique_violations = list(dict.fromkeys(violations))
        review = SecurityReview(
            approved=not unique_violations,
            checks_performed=list(_TRANSACTION_CHECKS),
            violations=unique_violations,
            recommendations=_unique_recommendations(unique_violations),
        )
        return AgentResult(self.name, review, 1.0)

    async def review_system(self, state: ApplicationState) -> AgentResult:
        """Validate a clone of the supplied aggregate without exposing its context."""

        if not isinstance(state, ApplicationState):
            raise TypeError("state must be an ApplicationState")
        try:
            cloned_state = state.clone()
            cloned_state.validate_invariants()
        except StateInvariantError:
            review = SecurityReview(
                approved=False,
                checks_performed=["application_state_invariants"],
                violations=["state_invariant_violation"],
                recommendations=[_RECOMMENDATIONS["state_invariant_violation"]],
            )
        else:
            review = SecurityReview(
                approved=True,
                checks_performed=["application_state_invariants"],
                violations=[],
                recommendations=[],
            )
        return AgentResult(self.name, review, 1.0)

    async def run(self, context: AgentContext) -> AgentResult:
        """Dispatch exactly one supported immutable security-review target."""

        if not isinstance(context, AgentContext):
            raise TypeError("context must be AgentContext")
        targets = set(context.payload)
        if targets == {"snapshot"}:
            snapshot = context.payload["snapshot"]
            if not isinstance(snapshot, TransactionSnapshot):
                raise TypeError("snapshot payload must be TransactionSnapshot")
            return await self.review_transaction(snapshot)
        if targets == {"state"}:
            state = context.payload["state"]
            if not isinstance(state, ApplicationState):
                raise TypeError("state payload must be ApplicationState")
            return await self.review_system(state)
        raise ValueError("payload must contain exactly one of snapshot or state")
