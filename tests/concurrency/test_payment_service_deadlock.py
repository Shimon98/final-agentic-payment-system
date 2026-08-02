"""Opposite-direction transfer deadlock prevention."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_opposite_direction_transfers_complete_within_timeout(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"USER-A": Decimal("100.00"), "USER-B": Decimal("100.00")}
        )
    )
    start = asyncio.Event()

    async def transfer(sender: str, receiver: str, key: str) -> None:
        await start.wait()
        await harness.service.transfer_money(
            sender_id=sender,
            receiver_id=receiver,
            amount=Decimal("10.00"),
            idempotency_key=key,
            correlation_id=f"CORR-{key}",
        )

    tasks = [
        asyncio.create_task(transfer("USER-A", "USER-B", "IDEMP-A-B")),
        asyncio.create_task(transfer("USER-B", "USER-A", "IDEMP-B-A")),
    ]
    start.set()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)

    state = harness.manager.current_state
    assert state.wallets["USER-A"].balance == Decimal("100.00")
    assert state.wallets["USER-B"].balance == Decimal("100.00")
    assert len(state.transactions) == 2
    assert harness.locks._locks == {}
