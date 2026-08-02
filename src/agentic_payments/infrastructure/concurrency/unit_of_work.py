"""Copy-on-write payment Unit of Work."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum, auto

from agentic_payments.application import ApplicationState
from agentic_payments.domain import AuditEvent

_CommitCallback = Callable[[ApplicationState], Awaitable[None]]


class _UnitOfWorkStatus(Enum):
    ACTIVE = auto()
    COMMITTED = auto()
    ROLLED_BACK = auto()


class PaymentUnitOfWork:
    """Own one mutable working-state clone for an explicit transaction."""

    _working_state: ApplicationState
    _commit_callback: _CommitCallback
    _status: _UnitOfWorkStatus

    def __init__(self) -> None:
        raise RuntimeError("PaymentUnitOfWork must be created by PaymentTransactionManager")

    @classmethod
    def _create(
        cls,
        *,
        working_state: ApplicationState,
        commit_callback: _CommitCallback,
    ) -> PaymentUnitOfWork:
        unit = object.__new__(cls)
        unit._working_state = working_state
        unit._commit_callback = commit_callback
        unit._status = _UnitOfWorkStatus.ACTIVE
        return unit

    def _require_active(self) -> None:
        if self._status is not _UnitOfWorkStatus.ACTIVE:
            raise RuntimeError("Unit of Work is no longer active")

    @property
    def state(self) -> ApplicationState:
        """Expose the mutable working state only while this Unit of Work is active."""

        self._require_active()
        return self._working_state

    def append_audit(self, event: AuditEvent) -> None:
        """Add one unique audit event to the transactional outbox."""

        self._require_active()
        if not isinstance(event, AuditEvent):
            raise TypeError("event must be an AuditEvent")
        if event.event_id in self._working_state.pending_audit_events:
            raise ValueError(f"duplicate audit event ID: {event.event_id}")
        self._working_state.pending_audit_events[event.event_id] = event

    def validate_invariants(self) -> None:
        """Delegate validation to the active application-state working copy."""

        self.state.validate_invariants()

    async def commit(self) -> None:
        """Validate and atomically commit this working state exactly once."""

        self._require_active()
        self.validate_invariants()
        await self._commit_callback(self._working_state)
        self._status = _UnitOfWorkStatus.COMMITTED

    async def rollback(self) -> None:
        """Invalidate an uncommitted working copy without changing committed state."""

        if self._status is _UnitOfWorkStatus.ACTIVE:
            self._status = _UnitOfWorkStatus.ROLLED_BACK
