"""Transfer behavior tests for PaymentDomainService."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from conftest import FIXED_TIME, DeterministicIdGenerator

from agentic_payments.domain import (
    IdempotencyConflictError,
    InsufficientFundsError,
    InvalidAmountError,
    PolicyViolationError,
    RiskLevel,
    SelfTransferError,
    StateInvariantError,
    Transaction,
    TransactionStatus,
    TransferPolicy,
    UserNotFoundError,
    WalletNotFoundError,
)


def _prior_transaction(
    transaction_id: str,
    *,
    sender_id: str = "SENDER",
    receiver_id: str = "RECEIVER",
    amount: Decimal = Decimal("10.00"),
    minutes_ago: int = 10,
) -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        sender_id=sender_id,
        receiver_id=receiver_id,
        amount=amount,
        created_at=FIXED_TIME - timedelta(minutes=minutes_ago),
        status=TransactionStatus.COMPLETED,
        risk_score=0,
        risk_level=RiskLevel.LOW,
        risk_reasons=(),
        failure_reason=None,
        correlation_id=f"CORR-{transaction_id}",
        idempotency_key=f"IDEMP-{transaction_id}",
    )


def _arguments(
    *,
    amount: object = Decimal("25.00"),
    idempotency_key: str = "IDEMP-TRANSFER",
) -> dict[str, Any]:
    return {
        "sender_id": "SENDER",
        "receiver_id": "RECEIVER",
        "amount": amount,
        "idempotency_key": idempotency_key,
        "correlation_id": "CORR-TRANSFER",
    }


@pytest.mark.asyncio
async def test_valid_transfer_updates_exact_balances_versions_and_transaction(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = application_state_factory({"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")})
    harness = payment_harness_factory(initial_state=state)

    snapshot = await harness.service.transfer_money(**_arguments())
    committed = harness.manager.current_state

    assert committed.wallets["SENDER"].balance == Decimal("75.00")
    assert committed.wallets["RECEIVER"].balance == Decimal("45.00")
    assert committed.wallets["SENDER"].version == 1
    assert committed.wallets["RECEIVER"].version == 1
    assert committed.transactions == {snapshot.transaction.transaction_id: snapshot.transaction}


@pytest.mark.asyncio
async def test_transfer_snapshot_equations_are_exact(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")}
        )
    )

    snapshot = await harness.service.transfer_money(**_arguments())

    assert snapshot.sender_balance_before == Decimal("100.00")
    assert snapshot.sender_balance_after == Decimal("75.00")
    assert snapshot.receiver_balance_before == Decimal("20.00")
    assert snapshot.receiver_balance_after == Decimal("45.00")
    assert snapshot.sender_balance_after == (
        snapshot.sender_balance_before - snapshot.transaction.amount
    )
    assert snapshot.receiver_balance_after == (
        snapshot.receiver_balance_before + snapshot.transaction.amount
    )


@pytest.mark.asyncio
async def test_recent_transfer_window_is_inclusive_and_sorted(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = application_state_factory(
        {
            "SENDER": Decimal("100.00"),
            "RECEIVER": Decimal("20.00"),
            "OTHER": Decimal("20.00"),
        }
    )
    state.transactions = {
        "T-30": _prior_transaction("T-30", minutes_ago=30),
        "T-31": _prior_transaction("T-31", minutes_ago=31),
        "T-10": _prior_transaction("T-10", receiver_id="OTHER", minutes_ago=10),
    }
    harness = payment_harness_factory(initial_state=state)

    snapshot = await harness.service.transfer_money(**_arguments())

    assert [item.transaction_id for item in snapshot.recent_sender_transactions] == [
        "T-30",
        "T-10",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [Decimal("-1.00"), Decimal("0")])
async def test_non_positive_transfer_amount_is_rejected(
    payment_harness_factory: Any,
    application_state_factory: Any,
    amount: Decimal,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")}
        )
    )

    with pytest.raises(InvalidAmountError):
        await harness.service.transfer_money(**_arguments(amount=amount))

    assert harness.repository.save_calls == 0


@pytest.mark.asyncio
async def test_float_transfer_amount_is_rejected(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")}
        )
    )

    with pytest.raises(InvalidAmountError):
        await harness.service.transfer_money(**_arguments(amount=25.0))


@pytest.mark.asyncio
async def test_self_transfer_is_rejected(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory({"SENDER": Decimal("100.00")})
    )

    with pytest.raises(SelfTransferError):
        await harness.service.transfer_money(
            sender_id="SENDER",
            receiver_id="SENDER",
            amount=Decimal("1.00"),
            idempotency_key="IDEMP-SELF",
            correlation_id="CORR-SELF",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sender_id", "receiver_id", "missing"),
    [
        ("MISSING", "RECEIVER", "MISSING"),
        ("SENDER", "MISSING", "MISSING"),
    ],
)
async def test_missing_transfer_participant_is_rejected(
    payment_harness_factory: Any,
    application_state_factory: Any,
    sender_id: str,
    receiver_id: str,
    missing: str,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")}
        )
    )

    with pytest.raises(UserNotFoundError) as captured:
        await harness.service.transfer_money(
            sender_id=sender_id,
            receiver_id=receiver_id,
            amount=Decimal("1.00"),
            idempotency_key="IDEMP-MISSING",
            correlation_id="CORR-MISSING",
        )

    assert captured.value.user_id == missing


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_wallet", ["SENDER", "RECEIVER"])
async def test_missing_transfer_wallet_is_rejected(
    payment_harness_factory: Any,
    application_state_factory: Any,
    missing_wallet: str,
) -> None:
    state = application_state_factory({"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")})
    del state.wallets[missing_wallet]
    harness = payment_harness_factory()

    class UnsafeUnit:
        def __init__(self) -> None:
            self.state = state

    class UnsafeTransactionManager:
        @asynccontextmanager
        async def transaction(self) -> AsyncIterator[Any]:
            yield UnsafeUnit()

    harness.service._transaction_manager = UnsafeTransactionManager()

    with pytest.raises(WalletNotFoundError) as captured:
        await harness.service.transfer_money(**_arguments())

    assert captured.value.user_id == missing_wallet


@pytest.mark.asyncio
async def test_insufficient_funds_changes_nothing(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("10.00"), "RECEIVER": Decimal("20.00")}
        )
    )

    with pytest.raises(InsufficientFundsError):
        await harness.service.transfer_money(**_arguments(amount=Decimal("11.00")))

    state = harness.manager.current_state
    assert state.wallets["SENDER"].balance == Decimal("10.00")
    assert state.transactions == {}
    assert state.idempotency_records == {}
    assert state.pending_audit_events == {}


@pytest.mark.asyncio
async def test_single_transfer_limit_is_enforced(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    policy = TransferPolicy(
        maximum_single_transfer=Decimal("20.00"),
        maximum_daily_transfer=Decimal("100.00"),
        suspicious_balance_ratio=Decimal("0.70"),
        rapid_transfer_window_minutes=30,
        rapid_transfer_count=3,
    )
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")}
        ),
        transfer_policy=policy,
    )

    with pytest.raises(PolicyViolationError):
        await harness.service.transfer_money(**_arguments(amount=Decimal("25.00")))


@pytest.mark.asyncio
async def test_rolling_daily_limit_is_enforced(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = application_state_factory({"SENDER": Decimal("200.00"), "RECEIVER": Decimal("20.00")})
    state.transactions["PRIOR"] = _prior_transaction(
        "PRIOR",
        amount=Decimal("60.00"),
        minutes_ago=60,
    )
    policy = TransferPolicy(
        maximum_single_transfer=Decimal("100.00"),
        maximum_daily_transfer=Decimal("100.00"),
        suspicious_balance_ratio=Decimal("0.70"),
        rapid_transfer_window_minutes=30,
        rapid_transfer_count=3,
    )
    harness = payment_harness_factory(initial_state=state, transfer_policy=policy)

    with pytest.raises(PolicyViolationError):
        await harness.service.transfer_money(**_arguments(amount=Decimal("50.00")))


@pytest.mark.asyncio
async def test_generated_transaction_id_collision_is_rejected(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    state = application_state_factory({"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")})
    state.transactions["EXISTING"] = _prior_transaction("EXISTING")
    ids = DeterministicIdGenerator(transaction_ids=["EXISTING"])
    harness = payment_harness_factory(initial_state=state, ids=ids)

    with pytest.raises(StateInvariantError, match="transaction ID already exists"):
        await harness.service.transfer_money(**_arguments())

    assert harness.repository.save_calls == 0
    assert harness.manager.current_state.wallets["SENDER"].balance == Decimal("100.00")


@pytest.mark.asyncio
async def test_transfer_commits_business_audit_and_idempotency_together(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")}
        )
    )

    snapshot = await harness.service.transfer_money(**_arguments())
    state = harness.manager.current_state

    assert snapshot.transaction.transaction_id in state.transactions
    assert "IDEMP-TRANSFER" in state.idempotency_records
    assert len(state.pending_audit_events) == 1
    event = next(iter(state.pending_audit_events.values()))
    assert event.action == "transferMoney"
    assert event.details["amount"] == "25.00"


@pytest.mark.asyncio
async def test_transfer_retry_returns_exact_snapshot_without_extra_save(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")}
        )
    )

    first = await harness.service.transfer_money(**_arguments())
    second = await harness.service.transfer_money(**_arguments())

    assert second == first
    assert second.recent_sender_transactions == first.recent_sender_transactions
    assert harness.repository.save_calls == 1
    assert harness.ids.transaction_calls == 1
    assert harness.ids.audit_event_calls == 1
    assert len(harness.manager.current_state.transactions) == 1


@pytest.mark.asyncio
async def test_transfer_same_key_different_amount_conflicts(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("20.00")}
        )
    )
    await harness.service.transfer_money(**_arguments(amount=Decimal("10.00")))

    with pytest.raises(IdempotencyConflictError):
        await harness.service.transfer_money(**_arguments(amount=Decimal("11.00")))

    assert harness.repository.save_calls == 1
