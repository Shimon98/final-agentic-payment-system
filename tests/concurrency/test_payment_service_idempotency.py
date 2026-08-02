"""Concurrent idempotency and normalized-phone tests."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from agentic_payments.domain import (
    DuplicatePhoneNumberError,
    IdempotencyConflictError,
    TransactionSnapshot,
    User,
)


@pytest.mark.asyncio
async def test_concurrent_identical_transfer_executes_once(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("0.00")}
        )
    )
    start = asyncio.Event()

    async def transfer() -> TransactionSnapshot:
        await start.wait()
        return await harness.service.transfer_money(
            sender_id="SENDER",
            receiver_id="RECEIVER",
            amount=Decimal("10.00"),
            idempotency_key="IDEMP-SAME",
            correlation_id="CORR-SAME",
        )

    tasks = [asyncio.create_task(transfer()), asyncio.create_task(transfer())]
    start.set()
    first, second = await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)

    assert first == second
    assert first.transaction.transaction_id == second.transaction.transaction_id
    assert harness.repository.save_calls == 1
    assert harness.ids.transaction_calls == 1
    assert len(harness.manager.current_state.transactions) == 1


@pytest.mark.asyncio
async def test_concurrent_same_key_different_fingerprint_conflicts(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("0.00")}
        )
    )
    start = asyncio.Event()

    async def transfer(amount: Decimal) -> TransactionSnapshot:
        await start.wait()
        return await harness.service.transfer_money(
            sender_id="SENDER",
            receiver_id="RECEIVER",
            amount=amount,
            idempotency_key="IDEMP-SAME",
            correlation_id="CORR-SAME",
        )

    tasks = [
        asyncio.create_task(transfer(Decimal("10.00"))),
        asyncio.create_task(transfer(Decimal("11.00"))),
    ]
    start.set()
    results = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=True),
        timeout=1.0,
    )

    assert sum(isinstance(result, TransactionSnapshot) for result in results) == 1
    assert sum(isinstance(result, IdempotencyConflictError) for result in results) == 1
    assert harness.repository.save_calls == 1
    assert len(harness.manager.current_state.transactions) == 1


@pytest.mark.asyncio
async def test_concurrent_equivalent_phone_formats_create_one_user(
    payment_harness_factory: Any,
) -> None:
    harness = payment_harness_factory()
    start = asyncio.Event()

    async def create(phone: str, key: str) -> User:
        await start.wait()
        return await harness.service.create_user(
            name=key,
            phone_number=phone,
            initial_balance=Decimal("1.00"),
            idempotency_key=key,
            correlation_id=f"CORR-{key}",
        )

    tasks = [
        asyncio.create_task(create("050-123-4567", "IDEMP-A")),
        asyncio.create_task(create("(050) 123 4567", "IDEMP-B")),
    ]
    start.set()
    results = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=True),
        timeout=1.0,
    )

    assert sum(isinstance(result, User) for result in results) == 1
    assert sum(isinstance(result, DuplicatePhoneNumberError) for result in results) == 1
    assert len(harness.manager.current_state.users) == 1
