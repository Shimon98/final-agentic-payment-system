"""Deterministic fraud scoring over immutable transaction snapshots."""

from __future__ import annotations

from decimal import Decimal

from agentic_payments.agents.base import AgentContext, BaseAgent
from agentic_payments.application import AgentResult, FraudAssessment
from agentic_payments.domain import (
    RiskLevel,
    TransactionSnapshot,
    TransactionStatus,
    TransferPolicy,
)


class FraudDetectionAgent(BaseAgent):
    """Calculate the authoritative fixed fraud score without mutating state."""

    def __init__(self, *, transfer_policy: TransferPolicy) -> None:
        if not isinstance(transfer_policy, TransferPolicy):
            raise TypeError("transfer_policy must be a TransferPolicy")
        self._transfer_policy = transfer_policy

    @property
    def name(self) -> str:
        """Return the stable fraud-agent identity."""

        return "FraudDetectionAgent"

    @staticmethod
    def _risk_level(score: int) -> RiskLevel:
        if score <= 29:
            return RiskLevel.LOW
        if score <= 59:
            return RiskLevel.MEDIUM
        return RiskLevel.HIGH

    async def assess_transaction(self, snapshot: TransactionSnapshot) -> AgentResult:
        """Score one immutable transaction snapshot using the approved rules."""

        if not isinstance(snapshot, TransactionSnapshot):
            raise TypeError("snapshot must be a TransactionSnapshot")
        transaction = snapshot.transaction
        score = 0
        reasons: list[str] = []
        maximum = self._transfer_policy.maximum_single_transfer

        if transaction.amount >= maximum * Decimal("0.80"):
            score += 25
            reasons.append("amount_near_single_transfer_limit")
        elif transaction.amount >= maximum * Decimal("0.50"):
            score += 10
            reasons.append("large_transfer_amount")

        balance_ratio = transaction.amount / snapshot.sender_balance_before
        if balance_ratio >= self._transfer_policy.suspicious_balance_ratio:
            score += 35
            reasons.append("high_balance_percentage")

        recent_transactions = tuple(
            recent
            for recent in snapshot.recent_sender_transactions
            if recent.transaction_id != transaction.transaction_id
        )
        recent_count = len(recent_transactions)
        if recent_count >= self._transfer_policy.rapid_transfer_count:
            score += 25
            reasons.append("rapid_transfer_activity")

        if any(recent.status is TransactionStatus.FLAGGED for recent in recent_transactions):
            score += 15
            reasons.append("recent_flagged_transaction")

        score = min(score, 100)
        risk_level = self._risk_level(score)
        requires_security_review = risk_level is RiskLevel.HIGH or 50 <= score <= 59
        assessment = FraudAssessment(
            transaction_id=transaction.transaction_id,
            risk_score=score,
            risk_level=risk_level,
            reasons=reasons,
            requires_security_review=requires_security_review,
        )
        return AgentResult(
            agent_name=self.name,
            output=assessment,
            confidence=1.0,
            metadata={
                "recent_transaction_count": recent_count,
                "sender_balance_before": format(snapshot.sender_balance_before, "f"),
                "calculated_balance_ratio": format(balance_ratio, "f"),
            },
        )

    async def run(self, context: AgentContext) -> AgentResult:
        """Assess the snapshot supplied in the immutable payload."""

        if not isinstance(context, AgentContext):
            raise TypeError("context must be AgentContext")
        snapshot = context.payload.get("snapshot")
        if not isinstance(snapshot, TransactionSnapshot):
            raise TypeError("context.payload['snapshot'] must be TransactionSnapshot")
        return await self.assess_transaction(snapshot)
