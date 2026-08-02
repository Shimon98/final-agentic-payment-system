"""Hebrew recovery guidance for typed domain and unknown failures."""

from __future__ import annotations

import re

from agentic_payments.agents.base import AgentContext, BaseAgent
from agentic_payments.application import AgentResult, ReflectionAdvice
from agentic_payments.domain import (
    IdempotencyConflictError,
    InsufficientFundsError,
    InvalidAmountError,
    PaymentRequestAlreadyResolvedError,
    PaymentRequestNotFoundError,
    PolicyViolationError,
    SelfTransferError,
    StateInvariantError,
    UserNotFoundError,
    WalletNotFoundError,
)


def _snake_case(class_name: str) -> str:
    first_pass = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", class_name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first_pass).lower()


class ReflectionAgent(BaseAgent):
    """Map failures to safe Hebrew advice without executing recovery."""

    @property
    def name(self) -> str:
        """Return the stable reflection-agent identity."""

        return "ReflectionAgent"

    async def reflect_on_error(
        self,
        error: Exception,
        context: AgentContext,
    ) -> AgentResult:
        """Return deterministic safe guidance for one supplied exception."""

        if not isinstance(error, Exception):
            raise TypeError("error must be an Exception")
        if not isinstance(context, AgentContext):
            raise TypeError("context must be AgentContext")

        suggested: dict[str, str] = {}
        confidence = 1.0
        if isinstance(error, InvalidAmountError):
            code = "invalid_amount"
            message = "הסכום חייב להיות ערך כספי חיובי ותקין."
            steps = ["יש לספק Decimal חיובי עם עד שתי ספרות אחרי הנקודה."]
        elif isinstance(error, InsufficientFundsError):
            code = "insufficient_funds"
            message = "היתרה הזמינה נמוכה מהסכום הנדרש."
            steps = ["יש לבחור סכום שאינו עולה על היתרה הזמינה."]
            suggested = {"amount": format(error.available, "f")}
        elif isinstance(error, SelfTransferError):
            code = "self_transfer"
            message = "השולח והמקבל חייבים להיות משתמשים שונים."
            steps = ["יש לבחור מזהה מקבל שונה ממזהה השולח."]
        elif isinstance(error, UserNotFoundError):
            code = "user_not_found"
            message = "המשתמש המבוקש אינו קיים."
            steps = ["יש לבדוק את מזהה המשתמש ולנסות בקשה חדשה."]
        elif isinstance(error, WalletNotFoundError):
            code = "wallet_not_found"
            message = "למשתמש המבוקש אין ארנק."
            steps = ["יש לבחור משתמש בעל ארנק תקין."]
        elif isinstance(error, PaymentRequestNotFoundError):
            code = "payment_request_not_found"
            message = "בקשת התשלום המבוקשת אינה קיימת."
            steps = ["יש לבדוק את מזהה בקשת התשלום."]
        elif isinstance(error, PaymentRequestAlreadyResolvedError):
            code = "payment_request_already_resolved"
            message = "בקשת התשלום כבר הוכרעה ואי אפשר להכריע אותה שוב."
            steps = ["יש לבדוק את מצב הבקשה הקיים לפני פעולה נוספת."]
        elif isinstance(error, PolicyViolationError):
            code = "policy_violation"
            message = "הפעולה חורגת ממגבלת המדיניות המאושרת."
            steps = ["יש לבחור סכום שאינו חורג מהמגבלה."]
            suggested = {"maximum_allowed": format(error.limit, "f")}
        elif isinstance(error, IdempotencyConflictError):
            code = "idempotency_conflict"
            message = "אותו מפתח אידמפוטנטיות שימש לפרמטרים שונים."
            steps = ["יש לתקן את הבקשה ולשלוח פעולה חדשה עם מפתח חדש."]
        elif isinstance(error, StateInvariantError):
            code = "state_invariant_error"
            message = "זוהתה בעיית עקביות פנימית במצב המערכת."
            steps = ["יש לעצור את הפעולה ולבצע בדיקת מערכת בטוחה."]
        else:
            code = _snake_case(type(error).__name__)
            message = "אירעה שגיאה שלא ניתן לפרט בבטחה."
            steps = ["יש לבדוק את הקלט ולנסות פעולה נתמכת חדשה."]
            confidence = 0.70

        advice = ReflectionAdvice(
            error_code=code,
            user_message=message,
            recovery_steps=steps,
            suggested_parameters=suggested,
        )
        return AgentResult(self.name, advice, confidence)

    async def run(self, context: AgentContext) -> AgentResult:
        """Reflect on the exception supplied in the immutable payload."""

        if not isinstance(context, AgentContext):
            raise TypeError("context must be AgentContext")
        error = context.payload.get("error")
        if not isinstance(error, Exception):
            raise TypeError("context.payload['error'] must be Exception")
        return await self.reflect_on_error(error, context)
