"""Concurrent-credit lost-update prevention through the global state gate."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_two_concurrent_credits_preserve_both_updates(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {
                "SENDER-A": Decimal("100.00"),
                "SENDER-B": Decimal("100.00"),
                "RECEIVER": Decimal("20.00"),
            }
        )
    )
    start = asyncio.Event()

    async def transfer(sender_id: str, key: str) -> None:
        await start.wait()
        await harness.service.transfer_money(
            sender_id=sender_id,
            receiver_id="RECEIVER",
            amount=Decimal("100.00"),
            idempotency_key=key,
            correlation_id=f"CORR-{key}",
        )

    tasks = [
        asyncio.create_task(transfer("SENDER-A", "IDEMP-A")),
        asyncio.create_task(transfer("SENDER-B", "IDEMP-B")),
    ]
    start.set()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)

    state = harness.manager.current_state
    assert state.wallets["SENDER-A"].balance == Decimal("0.00")
    assert state.wallets["SENDER-B"].balance == Decimal("0.00")
    assert state.wallets["RECEIVER"].balance == Decimal("220.00")
    assert len(state.transactions) == 2
