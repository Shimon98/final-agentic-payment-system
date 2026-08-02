"""Core PaymentFacade contracts over real deterministic services."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from agentic_payments.agents import (
    ExplanationAgent,
    FraudDetectionAgent,
    PolicyAgent,
    SecurityAgent,
)
from agentic_payments.application import (
    ApprovePaymentCommand,
    BusinessMemory,
    CheckBalanceCommand,
    CreateUserCommand,
    ExplainLastActionCommand,
    FraudAssessment,
    FraudCheckCommand,
    RejectPaymentCommand,
    RequestContext,
    RequestPaymentCommand,
    SecurityReview,
    SecurityReviewCommand,
    ShowTransactionsCommand,
    TransferMoneyCommand,
)
from agentic_payments.application.payment_facade import PaymentFacade
from agentic_payments.domain import RiskLevel, TransferPolicy

NOW = datetime(2026, 8, 2, 9, 0, tzinfo=UTC)


def _policy() -> TransferPolicy:
    return TransferPolicy(
        maximum_single_transfer=Decimal("10000.00"),
        maximum_daily_transfer=Decimal("20000.00"),
        suspicious_balance_ratio=Decimal("0.70"),
        rapid_transfer_window_minutes=30,
        rapid_transfer_count=3,
    )


def _context(key: str) -> RequestContext:
    return RequestContext(f"COR-{key}", key, NOW)


def _facade(harness: Any) -> PaymentFacade:
    policy = _policy()
    return PaymentFacade(
        payment_service=harness.service,
        transaction_manager=harness.manager,
        fraud_agent=FraudDetectionAgent(transfer_policy=policy),
        security_agent=SecurityAgent(),
        explanation_agent=ExplanationAgent(),
        policy_agent=PolicyAgent(transfer_policy=policy),
    )


@pytest.mark.asyncio
async def test_exact_outputs_for_seven_business_operations(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("500.00"), "RECEIVER": Decimal("20.00")}
        ),
        transfer_policy=_policy(),
    )
    facade = _facade(harness)

    created = await facade.create_user(
        CreateUserCommand("New User", "0501234567", Decimal("10.00"), _context("CREATE"))
    )
    balance = await facade.check_balance(CheckBalanceCommand("SENDER", _context("BALANCE")))
    transfer = await facade.transfer_money(
        TransferMoneyCommand("SENDER", "RECEIVER", Decimal("25.00"), _context("TRANSFER"))
    )
    pending = await facade.request_payment(
        RequestPaymentCommand("RECEIVER", "SENDER", Decimal("15.00"), _context("REQUEST"))
    )
    approved = await facade.approve_payment(
        ApprovePaymentCommand(pending.output["payment_request_id"], _context("APPROVE"))
    )
    another = await facade.request_payment(
        RequestPaymentCommand("RECEIVER", "SENDER", Decimal("5.00"), _context("REQUEST-2"))
    )
    rejected = await facade.reject_payment(
        RejectPaymentCommand(another.output["payment_request_id"], _context("REJECT"))
    )
    shown = await facade.show_transactions(ShowTransactionsCommand("SENDER", _context("SHOW")))

    assert set(created.output) == {"operation", "user_id", "user"}
    assert balance.output == {
        "operation": "checkBalance",
        "user_id": "SENDER",
        "balance": "500.00",
        "currency": "ILS",
    }
    assert set(transfer.output) == {
        "operation",
        "transaction_id",
        "snapshot",
        "fraud_assessment",
        "security_review",
        "post_processing_status",
    }
    assert set(pending.output) == {
        "operation",
        "payment_request_id",
        "payment_request",
    }
    assert set(approved.output) == {
        "operation",
        "payment_request_id",
        "transaction_id",
        "payment_request",
        "snapshot",
        "fraud_assessment",
        "security_review",
        "post_processing_status",
    }
    assert rejected.output["operation"] == "rejectPayment"
    assert shown.output["operation"] == "showTransactions"
    assert all(
        result.agent_name == "PaymentFacade"
        for result in (created, balance, transfer, pending, approved, rejected, shown)
    )


@pytest.mark.asyncio
async def test_specialist_results_are_preserved(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("0.00")}
        ),
        transfer_policy=_policy(),
    )
    facade = _facade(harness)
    transfer = await facade.transfer_money(
        TransferMoneyCommand("SENDER", "RECEIVER", Decimal("10.00"), _context("T"))
    )
    transaction_id = transfer.output["transaction_id"]

    fraud = await facade.fraud_check(FraudCheckCommand(transaction_id, _context("F")))
    security = await facade.security_review(SecurityReviewCommand(transaction_id, _context("S")))
    system = await facade.security_review(SecurityReviewCommand(None, _context("SYS")))
    explanation = await facade.explain_last_action(
        ExplainLastActionCommand(_context("E")),
        memory=BusinessMemory(last_transaction_id=transaction_id),
    )

    assert isinstance(fraud.output, FraudAssessment)
    assert fraud.output.risk_level is RiskLevel.LOW
    assert isinstance(security.output, SecurityReview)
    assert isinstance(system.output, SecurityReview)
    assert explanation.agent_name == "ExplanationAgent"


@pytest.mark.asyncio
async def test_every_public_operation_rejects_wrong_command(
    payment_harness_factory: Any,
) -> None:
    facade = _facade(payment_harness_factory(transfer_policy=_policy()))
    wrong = object()
    calls = (
        facade.create_user,
        facade.check_balance,
        facade.transfer_money,
        facade.request_payment,
        facade.approve_payment,
        facade.reject_payment,
        facade.show_transactions,
        facade.fraud_check,
        facade.security_review,
    )
    for call in calls:
        with pytest.raises(TypeError, match="command must be exactly"):
            await call(wrong)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="command must be exactly"):
        await facade.explain_last_action(wrong, memory=BusinessMemory())  # type: ignore[arg-type]
