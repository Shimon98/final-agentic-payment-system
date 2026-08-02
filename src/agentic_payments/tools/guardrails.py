"""Deterministic validation around payment-tool execution."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import Enum
from math import isfinite
from typing import Any

from agentic_payments.application.commands import (
    ApprovePaymentCommand,
    CheckBalanceCommand,
    CreateUserCommand,
    ExplainLastActionCommand,
    FraudCheckCommand,
    RejectPaymentCommand,
    RequestPaymentCommand,
    SecurityReviewCommand,
    ShowTransactionsCommand,
    TransferMoneyCommand,
)
from agentic_payments.application.results import (
    AgentResult,
    FraudAssessment,
    RouterDecision,
    SecurityReview,
)
from agentic_payments.domain import Intent

_CONTRACTS: dict[Intent, tuple[type[object], frozenset[str]]] = {
    Intent.CREATE_USER: (
        CreateUserCommand,
        frozenset({"name", "phone_number", "initial_balance"}),
    ),
    Intent.CHECK_BALANCE: (CheckBalanceCommand, frozenset({"user_id"})),
    Intent.TRANSFER_MONEY: (
        TransferMoneyCommand,
        frozenset({"sender_id", "receiver_id", "amount"}),
    ),
    Intent.REQUEST_PAYMENT: (
        RequestPaymentCommand,
        frozenset({"requester_id", "payer_id", "amount"}),
    ),
    Intent.APPROVE_PAYMENT: (ApprovePaymentCommand, frozenset({"request_id"})),
    Intent.REJECT_PAYMENT: (RejectPaymentCommand, frozenset({"request_id"})),
    Intent.SHOW_TRANSACTIONS: (ShowTransactionsCommand, frozenset({"user_id"})),
    Intent.FRAUD_CHECK: (FraudCheckCommand, frozenset({"transaction_id"})),
    Intent.SECURITY_REVIEW: (SecurityReviewCommand, frozenset({"transaction_id"})),
    Intent.EXPLAIN_LAST_ACTION: (ExplainLastActionCommand, frozenset()),
}

_EXPLANATION_FLOAT_FIELDS = {
    "confidence",
    "route_confidence",
    "confidence_threshold",
}
_MONEY_FIELD_PARTS = {
    "amount",
    "balance",
    "price",
    "funds",
    "limit",
    "currency",
}


def _json_without_float(
    value: Any,
    *,
    explanation: bool = False,
    path: tuple[str | None, ...] = (),
) -> None:
    if isinstance(value, float):
        terminal = path[-1] if path else None
        below_facts = len(path) >= 2 and path[0] == "facts"
        monetary = isinstance(terminal, str) and any(
            part in terminal.lower() for part in _MONEY_FIELD_PARTS
        )
        if (
            explanation
            and below_facts
            and terminal in _EXPLANATION_FLOAT_FIELDS
            and not monetary
            and isfinite(value)
        ):
            return
        raise ValueError("ordinary result output must not contain float values")
    if isinstance(value, bool):
        if (
            explanation
            and len(path) >= 2
            and path[0] == "facts"
            and path[-1] in _EXPLANATION_FLOAT_FIELDS
        ):
            raise ValueError("explanation confidence fields must not be bool")
        return
    if value is None or isinstance(value, (str, int)):
        return
    if isinstance(value, Decimal):
        raise ValueError("ordinary result output must serialize Decimal values")
    if isinstance(value, Enum):
        raise ValueError("ordinary result output must serialize Enum values")
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError("ordinary result mapping keys must be strings")
            _json_without_float(
                nested,
                explanation=explanation,
                path=(*path, key),
            )
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _json_without_float(
                item,
                explanation=explanation,
                path=(*path, None),
            )
        return
    raise ValueError("ordinary result output must be JSON-compatible")


class ToolGuardrails:
    """Validate exact route/command and result contracts without mutation."""

    def __init__(self, *, confidence_threshold: float = 0.80) -> None:
        if isinstance(confidence_threshold, bool) or not isinstance(
            confidence_threshold, (int, float)
        ):
            raise TypeError("confidence_threshold must be numeric and not bool")
        threshold = float(confidence_threshold)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        self._confidence_threshold = threshold

    def validate_before_execution(
        self,
        *,
        decision: RouterDecision,
        command: object,
    ) -> None:
        """Reject unclear, malformed, or mismatched tool input."""

        if not isinstance(decision, RouterDecision):
            raise ValueError("decision must be RouterDecision")
        if decision.intent is Intent.UNKNOWN:
            raise ValueError("UNKNOWN intent cannot execute a tool")
        if decision.confidence < self._confidence_threshold:
            raise ValueError("routing confidence is below the execution threshold")
        if decision.requires_clarification:
            raise ValueError("clarification is required before tool execution")
        expected, keys = _CONTRACTS[decision.intent]
        if type(command) is not expected:
            raise ValueError(f"command must be exactly {expected.__name__}")
        if frozenset(decision.parameters) != keys:
            raise ValueError("decision parameters do not match the intent contract")

    def validate_after_execution(
        self,
        *,
        intent: Intent,
        result: AgentResult,
    ) -> None:
        """Reject empty or incorrectly typed tool output."""

        if not isinstance(intent, Intent) or intent is Intent.UNKNOWN:
            raise ValueError("intent must be a supported Intent")
        if not isinstance(result, AgentResult):
            raise ValueError("result must be AgentResult")
        if not result.agent_name:
            raise ValueError("result agent_name must not be empty")
        output = result.output
        if (
            output is None
            or (isinstance(output, str) and not output.strip())
            or (isinstance(output, (Mapping, list, tuple)) and not output)
        ):
            raise ValueError("result output must not be empty")
        if intent is Intent.FRAUD_CHECK:
            if not isinstance(output, FraudAssessment):
                raise ValueError("fraudCheck output must be FraudAssessment")
            return
        if intent is Intent.SECURITY_REVIEW:
            if not isinstance(output, SecurityReview):
                raise ValueError("securityReview output must be SecurityReview")
            return
        if not isinstance(output, Mapping):
            raise ValueError("ordinary result output must be a mapping")
        _json_without_float(
            output,
            explanation=intent is Intent.EXPLAIN_LAST_ACTION,
        )
