"""Static intent-to-facade tool registry."""

from __future__ import annotations

from typing import TypeVar

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
from agentic_payments.application.memory_service import BusinessMemory
from agentic_payments.application.payment_facade import PaymentFacade
from agentic_payments.application.results import AgentResult
from agentic_payments.domain import Intent

_INTENTS = (
    Intent.CREATE_USER,
    Intent.CHECK_BALANCE,
    Intent.TRANSFER_MONEY,
    Intent.REQUEST_PAYMENT,
    Intent.APPROVE_PAYMENT,
    Intent.REJECT_PAYMENT,
    Intent.SHOW_TRANSACTIONS,
    Intent.FRAUD_CHECK,
    Intent.SECURITY_REVIEW,
    Intent.EXPLAIN_LAST_ACTION,
)

_TOOL_NAMES = {
    Intent.CREATE_USER: "create_user_tool",
    Intent.CHECK_BALANCE: "check_balance_tool",
    Intent.TRANSFER_MONEY: "transfer_money_tool",
    Intent.REQUEST_PAYMENT: "request_payment_tool",
    Intent.APPROVE_PAYMENT: "approve_payment_tool",
    Intent.REJECT_PAYMENT: "reject_payment_tool",
    Intent.SHOW_TRANSACTIONS: "show_transactions_tool",
    Intent.FRAUD_CHECK: "fraud_check_tool",
    Intent.SECURITY_REVIEW: "security_review_tool",
    Intent.EXPLAIN_LAST_ACTION: "explain_last_action_tool",
}

_CommandT = TypeVar("_CommandT")


class PaymentToolRegistry:
    """Dispatch each supported intent to exactly one typed facade operation."""

    def __init__(self, *, payment_facade: PaymentFacade) -> None:
        if not isinstance(payment_facade, PaymentFacade):
            raise TypeError("payment_facade must be PaymentFacade")
        self._payment_facade = payment_facade

    def tool_name_for_intent(self, intent: Intent) -> str:
        """Return the fixed tool name for one executable intent."""

        if not isinstance(intent, Intent):
            raise TypeError("intent must be Intent")
        try:
            return _TOOL_NAMES[intent]
        except KeyError as error:
            raise ValueError("UNKNOWN intent has no payment tool") from error

    def supported_intents(self) -> tuple[Intent, ...]:
        """Return all supported intents in their authoritative order."""

        return _INTENTS

    async def execute(
        self,
        *,
        intent: Intent,
        command: object,
        memory: BusinessMemory,
    ) -> AgentResult:
        """Execute exactly one statically selected facade operation."""

        if not isinstance(intent, Intent):
            raise TypeError("intent must be Intent")
        if not isinstance(memory, BusinessMemory):
            raise TypeError("memory must be BusinessMemory")
        if intent is Intent.CREATE_USER:
            return await self._payment_facade.create_user(self._exact(command, CreateUserCommand))
        if intent is Intent.CHECK_BALANCE:
            return await self._payment_facade.check_balance(
                self._exact(command, CheckBalanceCommand)
            )
        if intent is Intent.TRANSFER_MONEY:
            return await self._payment_facade.transfer_money(
                self._exact(command, TransferMoneyCommand)
            )
        if intent is Intent.REQUEST_PAYMENT:
            return await self._payment_facade.request_payment(
                self._exact(command, RequestPaymentCommand)
            )
        if intent is Intent.APPROVE_PAYMENT:
            return await self._payment_facade.approve_payment(
                self._exact(command, ApprovePaymentCommand)
            )
        if intent is Intent.REJECT_PAYMENT:
            return await self._payment_facade.reject_payment(
                self._exact(command, RejectPaymentCommand)
            )
        if intent is Intent.SHOW_TRANSACTIONS:
            return await self._payment_facade.show_transactions(
                self._exact(command, ShowTransactionsCommand)
            )
        if intent is Intent.FRAUD_CHECK:
            return await self._payment_facade.fraud_check(self._exact(command, FraudCheckCommand))
        if intent is Intent.SECURITY_REVIEW:
            return await self._payment_facade.security_review(
                self._exact(command, SecurityReviewCommand)
            )
        if intent is Intent.EXPLAIN_LAST_ACTION:
            return await self._payment_facade.explain_last_action(
                self._exact(command, ExplainLastActionCommand),
                memory=memory,
            )
        raise ValueError("UNKNOWN intent has no payment tool")

    @staticmethod
    def _exact(command: object, expected: type[_CommandT]) -> _CommandT:
        if type(command) is not expected:
            raise TypeError(f"command must be exactly {expected.__name__}")
        return command
