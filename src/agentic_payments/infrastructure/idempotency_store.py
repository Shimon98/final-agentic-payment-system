"""State-backed transactional implementation of the idempotency-store port."""

from __future__ import annotations

from agentic_payments.application import IdempotencyRecord
from agentic_payments.domain import IdempotencyConflictError
from agentic_payments.infrastructure.concurrency import (
    AsyncResourceLockManager,
    LockKey,
    LockScope,
    PaymentTransactionManager,
)


def _validate_key(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("idempotency_key must be a string")
    if not value or value != value.strip():
        raise ValueError("idempotency_key must be a non-empty stripped string")
    return value


class TransactionalIdempotencyStore:
    """Persist independent idempotency records through a transaction manager."""

    def __init__(
        self,
        *,
        transaction_manager: PaymentTransactionManager,
        lock_manager: AsyncResourceLockManager,
    ) -> None:
        if not isinstance(transaction_manager, PaymentTransactionManager):
            raise TypeError("transaction_manager must be a PaymentTransactionManager")
        if not isinstance(lock_manager, AsyncResourceLockManager):
            raise TypeError("lock_manager must be an AsyncResourceLockManager")
        self._transaction_manager = transaction_manager
        self._lock_manager = lock_manager

    async def get(self, idempotency_key: str) -> IdempotencyRecord | None:
        """Read one immutable record from an independent current-state clone."""

        key = _validate_key(idempotency_key)
        current_state = self._transaction_manager.current_state
        return current_state.idempotency_records.get(key)

    async def save(self, record: IdempotencyRecord) -> None:
        """Commit a new record, accept an equal retry, or reject a conflict."""

        if not isinstance(record, IdempotencyRecord):
            raise TypeError("record must be an IdempotencyRecord")
        lock_key = LockKey(LockScope.IDEMPOTENCY, record.idempotency_key)
        async with (
            self._lock_manager.acquire(lock_key),
            self._transaction_manager.transaction() as unit,
        ):
            existing = unit.state.idempotency_records.get(record.idempotency_key)
            if existing is None:
                unit.state.idempotency_records[record.idempotency_key] = record
                unit.validate_invariants()
                await unit.commit()
                return
            if existing != record:
                raise IdempotencyConflictError(record.idempotency_key)
