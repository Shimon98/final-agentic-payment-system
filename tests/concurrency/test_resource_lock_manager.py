"""Deterministic tests for asynchronous resource-lock management."""

from __future__ import annotations

import asyncio

import pytest

from agentic_payments.infrastructure.concurrency import (
    AsyncResourceLockManager,
    LockKey,
    LockScope,
)


@pytest.mark.asyncio
async def test_acquire_and_release_one_key() -> None:
    manager = AsyncResourceLockManager()
    key = LockKey(LockScope.WALLET, "A")

    async with manager.acquire(key):
        assert manager._locks[key].lock.locked()

    assert manager._locks == {}


@pytest.mark.asyncio
async def test_same_key_is_mutually_exclusive() -> None:
    manager = AsyncResourceLockManager()
    key = LockKey(LockScope.WALLET, "A")
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first() -> None:
        async with manager.acquire(key):
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        await first_entered.wait()
        async with manager.acquire(key):
            second_entered.set()

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await first_entered.wait()
    await asyncio.sleep(0)
    assert not second_entered.is_set()

    release_first.set()
    await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=1.0)
    assert second_entered.is_set()


@pytest.mark.asyncio
async def test_independent_keys_can_enter_concurrently() -> None:
    manager = AsyncResourceLockManager()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first() -> None:
        async with manager.acquire(LockKey(LockScope.WALLET, "A")):
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        await first_entered.wait()
        async with manager.acquire(LockKey(LockScope.WALLET, "B")):
            second_entered.set()

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await asyncio.wait_for(second_entered.wait(), timeout=1.0)
    assert not first_task.done()

    release_first.set()
    await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=1.0)


@pytest.mark.asyncio
async def test_duplicate_keys_are_reserved_and_acquired_once() -> None:
    manager = AsyncResourceLockManager()
    key = LockKey(LockScope.WALLET, "A")

    async with manager.acquire_many([key, key, key]):
        assert len(manager._locks) == 1
        assert manager._locks[key].references == 1

    assert manager._locks == {}


@pytest.mark.asyncio
async def test_empty_acquire_many_yields_immediately() -> None:
    manager = AsyncResourceLockManager()
    entered = False

    async with manager.acquire_many([]):
        entered = True

    assert entered
    assert manager._locks == {}


@pytest.mark.asyncio
async def test_acquisition_and_release_order_is_deterministic() -> None:
    manager = AsyncResourceLockManager()
    first = LockKey(LockScope.WALLET, "A")
    second = LockKey(LockScope.WALLET, "B")
    events: list[str] = []

    class RecordingLock:
        def __init__(self, name: str) -> None:
            self.name = name
            self._locked = False

        async def acquire(self) -> bool:
            events.append(f"acquire:{self.name}")
            self._locked = True
            return True

        def release(self) -> None:
            events.append(f"release:{self.name}")
            self._locked = False

        def locked(self) -> bool:
            return self._locked

    original_reserve = manager._reserve_entries

    async def reserve(keys: tuple[LockKey, ...]) -> tuple[object, ...]:
        entries = await original_reserve(keys)
        for key, entry in zip(keys, entries, strict=True):
            entry.lock = RecordingLock(key.resource_id)  # type: ignore[assignment]
        return entries

    manager._reserve_entries = reserve  # type: ignore[method-assign]

    async with manager.acquire_many([second, first]):
        events.append("inside")

    assert events == [
        "acquire:A",
        "acquire:B",
        "inside",
        "release:B",
        "release:A",
    ]


@pytest.mark.asyncio
async def test_exception_inside_context_releases_all_locks() -> None:
    manager = AsyncResourceLockManager()
    keys = [
        LockKey(LockScope.IDEMPOTENCY, "key"),
        LockKey(LockScope.WALLET, "A"),
    ]

    with pytest.raises(LookupError, match="boom"):
        async with manager.acquire_many(keys):
            raise LookupError("boom")

    assert manager._locks == {}
    async with asyncio.timeout(1.0):
        async with manager.acquire_many(keys):
            pass


@pytest.mark.asyncio
async def test_cancellation_while_waiting_releases_acquired_locks_and_references() -> None:
    manager = AsyncResourceLockManager()
    first = LockKey(LockScope.WALLET, "A")
    second = LockKey(LockScope.WALLET, "B")
    entries_reserved = asyncio.Event()
    original_reserve = manager._reserve_entries

    async def reserve(keys: tuple[LockKey, ...]) -> tuple[object, ...]:
        entries = await original_reserve(keys)
        if first in keys:
            entries_reserved.set()
        return entries

    manager._reserve_entries = reserve  # type: ignore[method-assign]

    async def waiting() -> None:
        async with manager.acquire_many([first, second]):
            raise AssertionError("cancelled task entered unexpectedly")

    async with manager.acquire(second):
        task = asyncio.create_task(waiting())
        await asyncio.wait_for(entries_reserved.wait(), timeout=1.0)
        await asyncio.sleep(0)
        assert manager._locks[first].lock.locked()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert first not in manager._locks

    assert manager._locks == {}


@pytest.mark.asyncio
async def test_later_acquisition_succeeds_after_waiter_cancellation() -> None:
    manager = AsyncResourceLockManager()
    first = LockKey(LockScope.WALLET, "A")
    second = LockKey(LockScope.WALLET, "B")
    entries_reserved = asyncio.Event()
    original_reserve = manager._reserve_entries

    async def reserve(keys: tuple[LockKey, ...]) -> tuple[object, ...]:
        entries = await original_reserve(keys)
        if first in keys:
            entries_reserved.set()
        return entries

    manager._reserve_entries = reserve  # type: ignore[method-assign]

    async with manager.acquire(second):
        task = asyncio.create_task(manager.acquire_many([first, second]).__aenter__())
        await asyncio.wait_for(entries_reserved.wait(), timeout=1.0)
        await asyncio.sleep(0)
        assert manager._locks[first].lock.locked()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async with asyncio.timeout(1.0):
        async with manager.acquire_many([second, first]):
            pass

    assert manager._locks == {}


@pytest.mark.asyncio
async def test_completed_operations_do_not_leak_registry_entries() -> None:
    manager = AsyncResourceLockManager()

    for index in range(50):
        async with manager.acquire(LockKey(LockScope.TRANSACTION, f"T-{index}")):
            pass

    assert manager._locks == {}


@pytest.mark.asyncio
async def test_invalid_collection_item_is_rejected() -> None:
    manager = AsyncResourceLockManager()

    with pytest.raises(TypeError, match="LockKey"):
        async with manager.acquire_many([LockKey(LockScope.WALLET, "A"), "invalid"]):  # type: ignore[list-item]
            pass

    assert manager._locks == {}
