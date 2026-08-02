"""Bilingual factual explanations over immutable memory and transactions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from agentic_payments.agents.base import AgentContext, BaseAgent
from agentic_payments.application import AgentResult, BusinessMemory
from agentic_payments.domain import Transaction, TransactionStatus

_SENSITIVE_KEY_PARTS = ("phone", "api_key", "secret", "prompt")


def _safe_value(value: Any, *, key: str = "") -> Any:
    if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(nested_key): _safe_value(nested, key=str(nested_key))
            for nested_key, nested in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, str) and re.fullmatch(r"\d{7,15}", value):
        return "[REDACTED]"
    return value


class ExplanationAgent(BaseAgent):
    """Explain stored facts without inventing reasons or financial outcomes."""

    @property
    def name(self) -> str:
        """Return the stable explanation-agent identity."""

        return "ExplanationAgent"

    async def explain_last_action(self, memory: BusinessMemory) -> AgentResult:
        """Explain only the latest facts present in immutable business memory."""

        if not isinstance(memory, BusinessMemory):
            raise TypeError("memory must be BusinessMemory")
        if memory.last_result is not None:
            facts = _safe_value(memory.last_result)
            output = {
                "message_he": "זוהי התוצאה האחרונה שנשמרה בזיכרון העסקי.",
                "message_en": "This is the latest result stored in business memory.",
                "facts": dict(facts),
            }
            return AgentResult(self.name, output, 0.95)

        reference_facts = {
            key: value
            for key, value in {
                "last_action": memory.last_action,
                "last_intent": memory.last_intent.value if memory.last_intent else None,
                "last_user_id": memory.last_user_id,
                "last_transaction_id": memory.last_transaction_id,
                "last_payment_request_id": memory.last_payment_request_id,
            }.items()
            if value is not None
        }
        if reference_facts:
            output = {
                "message_he": "נמצאה הפניה לפעולה האחרונה, ללא תוצאה מלאה.",
                "message_en": "A reference to the last action was found without a full result.",
                "facts": reference_facts,
            }
            return AgentResult(self.name, output, 0.75)

        output = {
            "message_he": "אין פעולה קודמת שניתן להסביר.",
            "message_en": "There is no previous action to explain.",
            "facts": {},
        }
        return AgentResult(self.name, output, 0.60)

    async def explain_transaction(self, transaction: Transaction) -> AgentResult:
        """Explain one concrete transaction using exactly its stored facts."""

        if not isinstance(transaction, Transaction):
            raise TypeError("transaction must be a Transaction")
        facts = {
            "transaction_id": transaction.transaction_id,
            "sender_id": transaction.sender_id,
            "receiver_id": transaction.receiver_id,
            "amount": format(transaction.amount, "f"),
            "status": transaction.status.value,
            "risk_score": transaction.risk_score,
            "risk_level": transaction.risk_level.value,
            "risk_reasons": list(transaction.risk_reasons),
            "failure_reason": transaction.failure_reason,
        }
        if transaction.status is TransactionStatus.FAILED:
            message_he = "העסקה נכשלה בהתאם לעובדות השמורות."
            message_en = "The transaction failed according to the stored facts."
        elif transaction.status is TransactionStatus.REJECTED:
            message_he = "העסקה נדחתה בהתאם לעובדות השמורות."
            message_en = "The transaction was rejected according to the stored facts."
        elif transaction.status is TransactionStatus.FLAGGED:
            message_he = "העסקה הושלמה וסומנה לבדיקה בהתאם לעובדות השמורות."
            message_en = "The transaction completed and was flagged according to stored facts."
        elif transaction.status is TransactionStatus.COMPLETED:
            message_he = "העסקה הושלמה בהתאם לעובדות השמורות."
            message_en = "The transaction completed according to the stored facts."
        else:
            message_he = "מצב העסקה מוצג בהתאם לעובדות השמורות."
            message_en = "The transaction status is shown according to the stored facts."
        output = {
            "message_he": message_he,
            "message_en": message_en,
            "facts": facts,
        }
        return AgentResult(self.name, output, 1.0)

    async def run(self, context: AgentContext) -> AgentResult:
        """Explain a supplied transaction, or fall back to immutable memory."""

        if not isinstance(context, AgentContext):
            raise TypeError("context must be AgentContext")
        if "transaction" in context.payload:
            transaction = context.payload["transaction"]
            if not isinstance(transaction, Transaction):
                raise TypeError("transaction payload must be Transaction")
            return await self.explain_transaction(transaction)
        return await self.explain_last_action(context.memory)
