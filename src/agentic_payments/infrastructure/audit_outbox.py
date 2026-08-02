"""Transactional audit-outbox delivery and idempotent retry coordination."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from agentic_payments.application import AuditRepository
from agentic_payments.domain import AuditEvent
from agentic_payments.infrastructure.concurrency.transaction_manager import (
    PaymentTransactionManager,
)
from agentic_payments.infrastructure.exceptions import (
    AuditPersistenceError,
    InfrastructureError,
    StatePersistenceError,
)


def _validate_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty stripped string")
    return value


def _validate_count(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class OutboxFailure:
    """One safe immutable failure encountered while flushing an event."""

    event_id: str
    error_type: str
    message: str

    def __post_init__(self) -> None:
        _validate_text(self.event_id, "event_id")
        _validate_text(self.error_type, "error_type")
        _validate_text(self.message, "message")


@dataclass(frozen=True, slots=True)
class OutboxFlushResult:
    """Immutable exact counts and failures from one flush attempt."""

    attempted: int
    delivered: int
    already_delivered: int
    removed: int
    failures: tuple[OutboxFailure, ...]
    pending_after: int

    def __post_init__(self) -> None:
        _validate_count(self.attempted, "attempted")
        _validate_count(self.delivered, "delivered")
        _validate_count(self.already_delivered, "already_delivered")
        _validate_count(self.removed, "removed")
        _validate_count(self.pending_after, "pending_after")
        if not isinstance(self.failures, tuple):
            raise TypeError("failures must be a tuple")
        if not all(isinstance(failure, OutboxFailure) for failure in self.failures):
            raise TypeError("failures must contain only OutboxFailure values")
        if self.removed > self.delivered + self.already_delivered:
            raise ValueError("removed cannot exceed delivered plus already_delivered")


class AuditOutboxDispatcher:
    """Deliver pending events to JSONL and remove only confirmed deliveries."""

    def __init__(
        self,
        *,
        transaction_manager: PaymentTransactionManager,
        audit_repository: AuditRepository,
    ) -> None:
        if not isinstance(transaction_manager, PaymentTransactionManager):
            raise TypeError("transaction_manager must be a PaymentTransactionManager")
        if not isinstance(audit_repository, AuditRepository):
            raise TypeError("audit_repository must satisfy AuditRepository")
        self._transaction_manager = transaction_manager
        self._audit_repository = audit_repository
        self._flush_lock = asyncio.Lock()

    @staticmethod
    def _safe_failure(event_id: str, error: Exception) -> OutboxFailure:
        message = (
            error.message
            if isinstance(error, InfrastructureError)
            else "Outbox event processing failed"
        )
        return OutboxFailure(
            event_id=event_id,
            error_type=type(error).__name__,
            message=message,
        )

    async def _remove_pending(self, expected: AuditEvent) -> None:
        async with self._transaction_manager.transaction() as unit:
            current = unit.state.pending_audit_events.get(expected.event_id)
            if current is None:
                return
            if current != expected:
                mismatch = ValueError("pending audit event content mismatch")
                raise StatePersistenceError(
                    "Pending audit event conflicts with expected content",
                    context={
                        "category": "event_id_conflict",
                        "event_id": expected.event_id,
                    },
                ) from mismatch
            del unit.state.pending_audit_events[expected.event_id]
            unit.validate_invariants()
            await unit.commit()

    async def flush_pending(self) -> OutboxFlushResult:
        """Flush an ordered initial snapshot and report exact retry-safe results."""

        async with self._flush_lock:
            await self._audit_repository.list_all()
            initial_state = self._transaction_manager.current_state
            events = sorted(
                initial_state.pending_audit_events.values(),
                key=lambda event: (event.occurred_at, event.event_id),
            )
            delivered = 0
            already_delivered = 0
            removed = 0
            failures: list[OutboxFailure] = []

            for event in events:
                try:
                    if self._audit_repository.contains_event_id(event.event_id):
                        await self._remove_pending(event)
                        already_delivered += 1
                        removed += 1
                        continue
                    await self._audit_repository.append(event)
                    if not self._audit_repository.contains_event_id(event.event_id):
                        missing = RuntimeError("event is absent from initialized audit index")
                        raise AuditPersistenceError(
                            "Audit delivery could not be confirmed",
                            context={
                                "category": "delivery_unconfirmed",
                                "event_id": event.event_id,
                            },
                        ) from missing
                    await self._remove_pending(event)
                    delivered += 1
                    removed += 1
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    failures.append(self._safe_failure(event.event_id, error))

            pending_after = len(self._transaction_manager.current_state.pending_audit_events)
            return OutboxFlushResult(
                attempted=len(events),
                delivered=delivered,
                already_delivered=already_delivered,
                removed=removed,
                failures=tuple(failures),
                pending_after=pending_after,
            )
