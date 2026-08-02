"""Tests for immutable request contexts and commands."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from agentic_payments.application import (
    ApprovePaymentCommand,
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

NOW = datetime(2026, 5, 1, 12, tzinfo=UTC)


def context() -> RequestContext:
    return RequestContext("COR-001", "IDEM-001", NOW)


def test_application_command_context_validation() -> None:
    assert context().actor == "user"
    with pytest.raises(ValueError):
        RequestContext(" COR", "IDEM", NOW)
    with pytest.raises(ValueError):
        RequestContext("COR", "IDEM", datetime(2026, 5, 1))


def test_application_command_constructs_all_ten_commands() -> None:
    commands = [
        CreateUserCommand("Diana", "0520000000", Decimal("0"), context()),
        CheckBalanceCommand("USR-001", context()),
        TransferMoneyCommand("USR-001", "USR-002", Decimal("1.00"), context()),
        RequestPaymentCommand("USR-002", "USR-001", Decimal("1.00"), context()),
        ApprovePaymentCommand("REQ-001", context()),
        RejectPaymentCommand("REQ-001", context()),
        ShowTransactionsCommand("USR-001", context()),
        FraudCheckCommand("TXN-001", context()),
        SecurityReviewCommand("TXN-001", context()),
        ExplainLastActionCommand(context()),
    ]
    assert len(commands) == 10
    assert SecurityReviewCommand(None, context()).transaction_id is None


@pytest.mark.parametrize("amount", [1.0, Decimal("NaN"), Decimal("Infinity"), Decimal("1.001")])
def test_application_command_rejects_invalid_money(amount: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        TransferMoneyCommand("USR-001", "USR-002", amount, context())


def test_application_command_initial_balance_rules() -> None:
    assert CreateUserCommand("Diana", "0520000000", Decimal("0"), context()).initial_balance == 0
    with pytest.raises(ValueError):
        CreateUserCommand("Diana", "0520000000", Decimal("-0.01"), context())


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1")])
def test_application_command_transfer_amount_must_be_positive(amount: Decimal) -> None:
    with pytest.raises(ValueError):
        TransferMoneyCommand("USR-001", "USR-002", amount, context())


def test_application_command_rejects_same_participants() -> None:
    with pytest.raises(ValueError):
        TransferMoneyCommand("USR-001", "USR-001", Decimal("1"), context())
    with pytest.raises(ValueError):
        RequestPaymentCommand("USR-001", "USR-001", Decimal("1"), context())


@pytest.mark.parametrize("phone", ["123456", "+972500000000", "050-0000000", "٠٥٢٠٠٠٠٠٠٠"])
def test_application_command_phone_must_be_normalized(phone: str) -> None:
    with pytest.raises(ValueError):
        CreateUserCommand("Diana", phone, Decimal("0"), context())
