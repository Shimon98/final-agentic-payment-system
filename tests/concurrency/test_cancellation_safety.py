"""Cancellation-safety tests for locks and state commits."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from agentic_payments.application import ApplicationState
from agentic_payments.domain import AuditEvent
from agentic_payments.infrastructure.concurrency import (
    AsyncResourceLockManager,
    LockKey,
    LockScope,
    PaymentTransactionManager,
)

FIXED_TIME = datetime(2026, 3, 4, 5, 6, tzinfo=UTC)


def _event(event_id: str) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        correlation_id="CORR-CANCEL",
        action="TEST",
        status="COMPLETED",
        occurred_at=FIXED_TIME,
        actor="test",
        details={},
    )


class BlockingStateRepository:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.block = True
        self.saved: list[ApplicationState] = []

    async def load(self) -> ApplicationState:
        return ApplicationState()

    async def save_atomic(self, state: ApplicationState) -> None:
        self.entered.set()
        if self.block:
            await self.release.wait()
        self.saved.append(state.clone())

    async def reset(self) -> None:
        self.saved.clear()


@pytest.mark.asyncio
async def test_cancellation_before_commit_rolls_back_and_reraises() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=BlockingStateRepository(),
    )
    entered = asyncio.Event()

    async def operation() -> None:
        async with manager.transaction() as unit:
            unit.append_audit(_event("NOT-COMMITTED"))
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(operation())
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert manager.current_state.pending_audit_events == {}


@pytest.mark.asyncio
async def test_cancellation_during_save_does_not_swap_state() -> None:
    repository = BlockingStateRepository()
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=repository,
    )

    async def operation() -> None:
        async with manager.transaction() as unit:
            unit.append_audit(_event("CANCELLED"))
            await unit.commit()

    task = asyncio.create_task(operation())
    await repository.entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert manager.current_state.pending_audit_events == {}
    assert repository.saved == []


@pytest.mark.asyncio
async def test_transaction_gate_releases_and_new_transaction_succeeds_after_cancellation() -> None:
    repository = BlockingStateRepository()
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=repository,
    )

    async def cancelled_operation() -> None:
        async with manager.transaction() as unit:
            unit.append_audit(_event("CANCELLED"))
            await unit.commit()

    task = asyncio.create_task(cancelled_operation())
    await repository.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    repository.block = False
    repository.entered.clear()
    async with asyncio.timeout(1.0):
        async with manager.transaction() as unit:
            unit.append_audit(_event("RECOVERED"))
            await unit.commit()

    assert set(manager.current_state.pending_audit_events) == {"RECOVERED"}


@pytest.mark.asyncio
async def test_successful_save_and_state_swap_have_no_cancellation_await_gap() -> None:
    class CancelAfterSaveRepository(BlockingStateRepository):
        async def save_atomic(self, state: ApplicationState) -> None:
            self.saved.append(state.clone())
            task = asyncio.current_task()
            assert task is not None
            asyncio.get_running_loop().call_soon(task.cancel)

    repository = CancelAfterSaveRepository()
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=repository,
    )

    async def operation() -> None:
        async with manager.transaction() as unit:
            unit.append_audit(_event("SAVED"))
            await unit.commit()

    task = asyncio.create_task(operation())
    await task
    assert not task.cancelled()
    assert set(manager.current_state.pending_audit_events) == {"SAVED"}


@pytest.mark.asyncio
async def test_cancelled_multi_lock_waiter_releases_first_lock() -> None:
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

    async def waiter() -> None:
        async with manager.acquire_many([first, second]):
            raise AssertionError("cancelled waiter entered")

    async with manager.acquire(second):
        task = asyncio.create_task(waiter())
        await asyncio.wait_for(entries_reserved.wait(), timeout=1.0)
        await asyncio.sleep(0)
        assert manager._locks[first].lock.locked()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert first not in manager._locks


@pytest.mark.asyncio
async def test_same_keys_can_be_acquired_after_cancelled_waiter() -> None:
    manager = AsyncResourceLockManager()
    first = LockKey(LockScope.TRANSACTION, "A")
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

        async def waiter() -> None:
            async with manager.acquire_many([first, second]):
                pass

        task = asyncio.create_task(waiter())
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
