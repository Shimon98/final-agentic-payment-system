"""Integration tests for the independent transactional idempotency adapter."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from conftest import InMemoryStateRepository

from agentic_payments.application import ApplicationState, IdempotencyRecord, IdempotencyStore
from agentic_payments.application.payment_domain_service import PaymentDomainService
from agentic_payments.domain import IdempotencyConflictError
from agentic_payments.infrastructure import TransactionalIdempotencyStore
from agentic_payments.infrastructure.concurrency import (
    AsyncResourceLockManager,
    LockKey,
    LockScope,
    PaymentTransactionManager,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _record(key: str, *, reference: str = "REF-1") -> IdempotencyRecord:
    return IdempotencyRecord(
        idempotency_key=key,
        operation_type="independent_operation",
        request_fingerprint="a" * 64,
        result_reference=reference,
        created_at=NOW,
    )


def _store(
    *,
    state: ApplicationState | None = None,
    repository: InMemoryStateRepository | None = None,
    locks: AsyncResourceLockManager | None = None,
) -> tuple[
    TransactionalIdempotencyStore,
    PaymentTransactionManager,
    InMemoryStateRepository,
]:
    chosen_repository = repository or InMemoryStateRepository()
    manager = PaymentTransactionManager(
        initial_state=state or ApplicationState(),
        state_repository=chosen_repository,
    )
    store = TransactionalIdempotencyStore(
        transaction_manager=manager,
        lock_manager=locks or AsyncResourceLockManager(),
    )
    return store, manager, chosen_repository


@pytest.mark.asyncio
async def test_get_missing_and_existing_performs_no_save() -> None:
    record = _record("IDEM-1")
    state = ApplicationState(idempotency_records={record.idempotency_key: record})
    store, _, repository = _store(state=state)

    assert isinstance(store, IdempotencyStore)
    assert await store.get("MISSING") is None
    assert await store.get("IDEM-1") == record
    assert repository.save_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["", " ", " leading", "trailing "])
async def test_get_rejects_invalid_key(key: str) -> None:
    store, _, _ = _store()
    with pytest.raises(ValueError):
        await store.get(key)


@pytest.mark.asyncio
async def test_save_new_record_commits_without_audit() -> None:
    store, manager, repository = _store()
    record = _record("IDEM-1")

    await store.save(record)

    assert manager.current_state.idempotency_records == {"IDEM-1": record}
    assert manager.current_state.pending_audit_events == {}
    assert repository.save_calls == 1


@pytest.mark.asyncio
async def test_equal_repeated_save_is_noop() -> None:
    store, _, repository = _store()
    record = _record("IDEM-1")

    await store.save(record)
    await store.save(record)

    assert repository.save_calls == 1


@pytest.mark.asyncio
async def test_conflicting_repeated_save_raises() -> None:
    store, manager, repository = _store()
    await store.save(_record("IDEM-1", reference="REF-1"))

    with pytest.raises(IdempotencyConflictError):
        await store.save(_record("IDEM-1", reference="REF-2"))

    assert manager.current_state.idempotency_records["IDEM-1"].result_reference == "REF-1"
    assert repository.save_calls == 1


class _RecordingLockManager(AsyncResourceLockManager):
    def __init__(self) -> None:
        super().__init__()
        self.keys: list[LockKey] = []

    @asynccontextmanager
    async def acquire(self, key: LockKey) -> AsyncIterator[None]:
        self.keys.append(key)
        async with super().acquire(key):
            yield


@pytest.mark.asyncio
async def test_save_acquires_exact_idempotency_lock_key() -> None:
    locks = _RecordingLockManager()
    store, _, _ = _store(locks=locks)

    await store.save(_record("IDEM-EXACT"))

    assert locks.keys == [LockKey(LockScope.IDEMPOTENCY, "IDEM-EXACT")]


@pytest.mark.asyncio
async def test_concurrent_equal_save_commits_once() -> None:
    store, manager, repository = _store()
    record = _record("IDEM-SAME")

    await asyncio.wait_for(
        asyncio.gather(store.save(record), store.save(record)),
        timeout=1.0,
    )

    assert manager.current_state.idempotency_records == {"IDEM-SAME": record}
    assert repository.save_calls == 1


@pytest.mark.asyncio
async def test_concurrent_conflicting_save_has_one_success_one_conflict() -> None:
    store, manager, repository = _store()
    first = _record("IDEM-CONFLICT", reference="REF-A")
    second = _record("IDEM-CONFLICT", reference="REF-B")

    results = await asyncio.wait_for(
        asyncio.gather(store.save(first), store.save(second), return_exceptions=True),
        timeout=1.0,
    )

    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, IdempotencyConflictError) for result in results) == 1
    assert repository.save_calls == 1
    assert manager.current_state.pending_audit_events == {}


def test_payment_domain_service_does_not_use_transactional_adapter() -> None:
    source = inspect.getsource(PaymentDomainService)
    assert "TransactionalIdempotencyStore" not in source
