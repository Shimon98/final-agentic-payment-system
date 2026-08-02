"""Static PaymentToolRegistry mapping and dispatch tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from agentic_payments.application import (
    AgentResult,
    ApprovePaymentCommand,
    BusinessMemory,
    CheckBalanceCommand,
    CreateUserCommand,
    ExplainLastActionCommand,
    FraudCheckCommand,
    RejectPaymentCommand,
    RequestContext,
    RequestPaymentCommand,
    SecurityReviewCommand,
    ShowTransactionsCommand,
    TransferMoneyCommand,
)
from agentic_payments.application.payment_facade import PaymentFacade
from agentic_payments.domain import Intent
from agentic_payments.tools import PaymentToolRegistry

NOW = datetime(2026, 8, 2, 11, 0, tzinfo=UTC)
CONTEXT = RequestContext("COR", "IDEMP", NOW)


def _registry() -> tuple[PaymentToolRegistry, PaymentFacade]:
    facade = PaymentFacade.__new__(PaymentFacade)
    for method in (
        "create_user",
        "check_balance",
        "transfer_money",
        "request_payment",
        "approve_payment",
        "reject_payment",
        "show_transactions",
        "fraud_check",
        "security_review",
        "explain_last_action",
    ):
        setattr(facade, method, AsyncMock(return_value=AgentResult("Spy", {"ok": True})))
    return PaymentToolRegistry(payment_facade=facade), facade


def test_exact_mapping_and_supported_order() -> None:
    registry, _ = _registry()
    expected = (
        (Intent.CREATE_USER, "create_user_tool"),
        (Intent.CHECK_BALANCE, "check_balance_tool"),
        (Intent.TRANSFER_MONEY, "transfer_money_tool"),
        (Intent.REQUEST_PAYMENT, "request_payment_tool"),
        (Intent.APPROVE_PAYMENT, "approve_payment_tool"),
        (Intent.REJECT_PAYMENT, "reject_payment_tool"),
        (Intent.SHOW_TRANSACTIONS, "show_transactions_tool"),
        (Intent.FRAUD_CHECK, "fraud_check_tool"),
        (Intent.SECURITY_REVIEW, "security_review_tool"),
        (Intent.EXPLAIN_LAST_ACTION, "explain_last_action_tool"),
    )

    assert registry.supported_intents() == tuple(intent for intent, _ in expected)
    assert tuple(registry.tool_name_for_intent(intent) for intent, _ in expected) == tuple(
        name for _, name in expected
    )
    with pytest.raises(ValueError, match="UNKNOWN"):
        registry.tool_name_for_intent(Intent.UNKNOWN)


@pytest.mark.asyncio
async def test_all_intents_dispatch_exactly_once_and_memory_only_for_explanation() -> None:
    registry, facade = _registry()
    cases = (
        (Intent.CREATE_USER, CreateUserCommand("Name", "0501234567", Decimal("1"), CONTEXT)),
        (Intent.CHECK_BALANCE, CheckBalanceCommand("U1", CONTEXT)),
        (Intent.TRANSFER_MONEY, TransferMoneyCommand("U1", "U2", Decimal("1"), CONTEXT)),
        (Intent.REQUEST_PAYMENT, RequestPaymentCommand("U1", "U2", Decimal("1"), CONTEXT)),
        (Intent.APPROVE_PAYMENT, ApprovePaymentCommand("R1", CONTEXT)),
        (Intent.REJECT_PAYMENT, RejectPaymentCommand("R1", CONTEXT)),
        (Intent.SHOW_TRANSACTIONS, ShowTransactionsCommand("U1", CONTEXT)),
        (Intent.FRAUD_CHECK, FraudCheckCommand("T1", CONTEXT)),
        (Intent.SECURITY_REVIEW, SecurityReviewCommand(None, CONTEXT)),
        (Intent.EXPLAIN_LAST_ACTION, ExplainLastActionCommand(CONTEXT)),
    )
    memory = BusinessMemory()

    for intent, command in cases:
        await registry.execute(intent=intent, command=command, memory=memory)

    calls = [
        facade.create_user,
        facade.check_balance,
        facade.transfer_money,
        facade.request_payment,
        facade.approve_payment,
        facade.reject_payment,
        facade.show_transactions,
        facade.fraud_check,
        facade.security_review,
        facade.explain_last_action,
    ]
    assert all(call.await_count == 1 for call in calls)
    facade.explain_last_action.assert_awaited_once_with(cases[-1][1], memory=memory)


@pytest.mark.asyncio
async def test_unknown_and_wrong_command_are_rejected_without_dispatch() -> None:
    registry, facade = _registry()
    with pytest.raises(ValueError, match="UNKNOWN"):
        await registry.execute(
            intent=Intent.UNKNOWN,
            command=object(),
            memory=BusinessMemory(),
        )
    with pytest.raises(TypeError, match="CreateUserCommand"):
        await registry.execute(
            intent=Intent.CREATE_USER,
            command=CheckBalanceCommand("U1", CONTEXT),
            memory=BusinessMemory(),
        )
    assert facade.create_user.await_count == 0
