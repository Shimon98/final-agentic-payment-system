"""Deadlock-prevention tests for opposite caller lock order."""

from __future__ import annotations

import asyncio

import pytest

from agentic_payments.infrastructure.concurrency import (
    AsyncResourceLockManager,
    LockKey,
    LockScope,
)


@pytest.mark.asyncio
async def test_opposite_wallet_order_completes_without_deadlock_or_overlap() -> None:
    manager = AsyncResourceLockManager()
    wallet_a = LockKey(LockScope.WALLET, "A")
    wallet_b = LockKey(LockScope.WALLET, "B")
    start = asyncio.Event()
    active = 0
    maximum_active = 0
    completed: list[str] = []

    async def operation(name: str, keys: list[LockKey]) -> None:
        nonlocal active, maximum_active
        await start.wait()
        async with manager.acquire_many(keys):
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0)
            completed.append(name)
            active -= 1

    tasks = [
        asyncio.create_task(operation("forward", [wallet_a, wallet_b])),
        asyncio.create_task(operation("reverse", [wallet_b, wallet_a])),
    ]
    start.set()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)

    assert sorted(completed) == ["forward", "reverse"]
    assert maximum_active == 1
    assert manager._locks == {}


@pytest.mark.asyncio
async def test_mixed_scope_opposite_order_uses_natural_lock_order() -> None:
    manager = AsyncResourceLockManager()
    idempotency = LockKey(LockScope.IDEMPOTENCY, "same")
    wallet = LockKey(LockScope.WALLET, "A")
    completed = 0

    async def operation(keys: list[LockKey]) -> None:
        nonlocal completed
        async with manager.acquire_many(keys):
            completed += 1
            await asyncio.sleep(0)

    await asyncio.wait_for(
        asyncio.gather(
            operation([wallet, idempotency]),
            operation([idempotency, wallet]),
        ),
        timeout=1.0,
    )

    assert completed == 2
    assert manager._locks == {}
