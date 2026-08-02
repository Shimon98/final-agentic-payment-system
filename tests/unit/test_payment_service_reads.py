"""Deterministic read-operation tests for PaymentDomainService."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from conftest import FIXED_TIME

from agentic_payments.domain import (
    RiskLevel,
    Transaction,
    TransactionStatus,
    UserNotFoundError,
    WalletNotFoundError,
)


def _transaction(
    transaction_id: str,
    *,
    sender_id: str,
    receiver_id: str,
    minutes: int,
) -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        sender_id=sender_id,
        receiver_id=receiver_id,
        amount=Decimal("1.00"),
        created_at=FIXED_TIME + timedelta(minutes=minutes),
        status=TransactionStatus.COMPLETED,
        risk_score=0,
        risk_level=RiskLevel.LOW,
        risk_reasons=(),
        failure_reason=None,
        correlation_id=f"CORR-{transaction_id}",
        idempotency_key=f"IDEMP-{transaction_id}",
    )


@pytest.mark.asyncio
async def test_get_balance_for_valid_user(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory({"U1": Decimal("12.34")})
    )

    assert await harness.service.get_balance(user_id="U1") == Decimal("12.34")


@pytest.mark.asyncio
async def test_get_balance_missing_user_raises(payment_harness_factory: Any) -> None:
    harness = payment_harness_factory()

    with pytest.raises(UserNotFoundError):
        await harness.service.get_balance(user_id="MISSING")


@pytest.mark.asyncio
async def test_get_balance_missing_wallet_raises(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = application_state_factory({"U1": Decimal("1.00")})
    del state.wallets["U1"]
    harness = payment_harness_factory()

    class MissingWalletStateProvider:
        @property
        def current_state(self) -> Any:
            return state

    harness.service._transaction_manager = MissingWalletStateProvider()

    with pytest.raises(WalletNotFoundError):
        await harness.service.get_balance(user_id="U1")


@pytest.mark.asyncio
async def test_transaction_history_includes_sender_and_receiver(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = application_state_factory(
        {"U1": Decimal("10"), "U2": Decimal("10"), "U3": Decimal("10")}
    )
    state.transactions = {
        "T1": _transaction("T1", sender_id="U1", receiver_id="U2", minutes=1),
        "T2": _transaction("T2", sender_id="U3", receiver_id="U1", minutes=2),
        "T3": _transaction("T3", sender_id="U2", receiver_id="U3", minutes=3),
    }
    harness = payment_harness_factory(initial_state=state)

    result = await harness.service.get_transactions(user_id="U1")

    assert [transaction.transaction_id for transaction in result] == ["T2", "T1"]


@pytest.mark.asyncio
async def test_transaction_history_is_newest_first_with_id_tiebreak(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = application_state_factory({"U1": Decimal("10"), "U2": Decimal("10")})
    state.transactions = {
        "T-A": _transaction("T-A", sender_id="U1", receiver_id="U2", minutes=1),
        "T-B": _transaction("T-B", sender_id="U1", receiver_id="U2", minutes=1),
        "T-C": _transaction("T-C", sender_id="U1", receiver_id="U2", minutes=2),
    }
    harness = payment_harness_factory(initial_state=state)

    result = await harness.service.get_transactions(user_id="U1")

    assert [transaction.transaction_id for transaction in result] == ["T-C", "T-B", "T-A"]


@pytest.mark.asyncio
async def test_reads_do_not_persist_or_create_audits(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = application_state_factory({"U1": Decimal("10"), "U2": Decimal("10")})
    state.transactions["T1"] = _transaction(
        "T1",
        sender_id="U1",
        receiver_id="U2",
        minutes=1,
    )
    harness = payment_harness_factory(initial_state=state)

    await harness.service.get_balance(user_id="U1")
    await harness.service.get_transactions(user_id="U1")

    assert harness.repository.save_calls == 0
    assert harness.manager.current_state.pending_audit_events == {}
