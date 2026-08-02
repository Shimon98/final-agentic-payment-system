"""Deterministic completeness and quality criticism for agent results."""

from __future__ import annotations

from collections.abc import Mapping

from agentic_payments.agents.base import AgentContext, BaseAgent
from agentic_payments.application import (
    AgentResult,
    CriticReview,
    FraudAssessment,
    SecurityReview,
)
from agentic_payments.domain import Intent, RiskLevel


def _is_empty(output: object) -> bool:
    if output is None:
        return True
    if isinstance(output, str):
        return not output.strip()
    if isinstance(output, Mapping):
        return not output
    if isinstance(output, (list, tuple)):
        return not output
    return False


class CriticAgent(BaseAgent):
    """Score result completeness without re-executing any business operation."""

    @property
    def name(self) -> str:
        """Return the stable critic-agent identity."""

        return "CriticAgent"

    async def review(self, result: AgentResult, expected_intent: Intent) -> AgentResult:
        """Apply the exact ordered penalty rules to one result."""

        if not isinstance(result, AgentResult):
            raise TypeError("result must be AgentResult")
        if not isinstance(expected_intent, Intent):
            raise TypeError("expected_intent must be Intent")

        problems: list[str] = []
        penalties: dict[str, int] = {}

        if _is_empty(result.output):
            problems.append("empty_output")
            penalties["empty_output"] = 3
        if result.confidence < 0.50:
            problems.append("low_confidence")
            penalties["low_confidence"] = 2

        expected_type: type[FraudAssessment] | type[SecurityReview] | None = None
        if expected_intent is Intent.FRAUD_CHECK:
            expected_type = FraudAssessment
        elif expected_intent is Intent.SECURITY_REVIEW:
            expected_type = SecurityReview
        if expected_type is not None and not isinstance(result.output, expected_type):
            problems.append("unexpected_output_type")
            penalties["unexpected_output_type"] = 2

        if isinstance(result.output, SecurityReview) and not result.output.approved:
            problems.append("security_review_rejected")
            penalties["security_review_rejected"] = 1
        if (
            isinstance(result.output, FraudAssessment)
            and result.output.risk_level is RiskLevel.HIGH
        ):
            problems.append("high_fraud_risk")
            penalties["high_fraud_risk"] = 1

        quality_score = max(1, 5 - sum(penalties.values()))
        must_fallback = (
            "empty_output" in penalties
            or "unexpected_output_type" in penalties
            or quality_score <= 2
        )
        review = CriticReview(
            approved=not must_fallback,
            quality_score=quality_score,
            problems=problems,
            requires_fallback=must_fallback,
        )
        return AgentResult(self.name, review, 1.0)

    async def run(self, context: AgentContext) -> AgentResult:
        """Review the typed result and expected intent supplied in payload."""

        if not isinstance(context, AgentContext):
            raise TypeError("context must be AgentContext")
        result = context.payload.get("result")
        expected_intent = context.payload.get("expected_intent")
        if not isinstance(result, AgentResult):
            raise TypeError("context.payload['result'] must be AgentResult")
        if not isinstance(expected_intent, Intent):
            raise TypeError("context.payload['expected_intent'] must be Intent")
        return await self.review(result, expected_intent)
