"""Concurrent double-spending prevention through the payment service."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from agentic_payments.domain import InsufficientFundsError, TransactionSnapshot


@pytest.mark.asyncio
async def test_two_withdrawals_of_eighty_allow_exactly_one(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {
                "SENDER": Decimal("100.00"),
                "RECEIVER-A": Decimal("0.00"),
                "RECEIVER-B": Decimal("0.00"),
            }
        )
    )
    start = asyncio.Event()

    async def transfer(receiver_id: str, key: str) -> TransactionSnapshot:
        await start.wait()
        return await harness.service.transfer_money(
            sender_id="SENDER",
            receiver_id=receiver_id,
            amount=Decimal("80.00"),
            idempotency_key=key,
            correlation_id=f"CORR-{key}",
        )

    tasks = [
        asyncio.create_task(transfer("RECEIVER-A", "IDEMP-A")),
        asyncio.create_task(transfer("RECEIVER-B", "IDEMP-B")),
    ]
    start.set()
    results = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=True),
        timeout=1.0,
    )

    assert sum(isinstance(result, TransactionSnapshot) for result in results) == 1
    assert sum(isinstance(result, InsufficientFundsError) for result in results) == 1
    state = harness.manager.current_state
    assert state.wallets["SENDER"].balance == Decimal("20.00")
    assert len(state.transactions) == 1
    assert len(state.idempotency_records) == 1
    assert len(state.pending_audit_events) == 1
