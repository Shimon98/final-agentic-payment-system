"""Application-facing protocols for time, IDs, and persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from agentic_payments.application.state import ApplicationState, IdempotencyRecord
from agentic_payments.domain import AuditEvent


@runtime_checkable
class Clock(Protocol):
    """Provide timezone-aware application time."""

    def now(self) -> datetime: ...


@runtime_checkable
class IdGenerator(Protocol):
    """Generate identifiers required by application operations."""

    def new_user_id(self) -> str: ...

    def new_transaction_id(self) -> str: ...

    def new_payment_request_id(self) -> str: ...

    def new_audit_event_id(self) -> str: ...

    def new_correlation_id(self) -> str: ...


@runtime_checkable
class StateRepository(Protocol):
    """Load and atomically persist complete application state."""

    async def load(self) -> ApplicationState: ...

    async def save_atomic(self, state: ApplicationState) -> None: ...

    async def reset(self) -> None: ...


@runtime_checkable
class AuditRepository(Protocol):
    """Append and query idempotently delivered audit events."""

    async def append(self, event: AuditEvent) -> None: ...

    async def list_all(self) -> list[AuditEvent]: ...

    async def find_by_correlation_id(self, correlation_id: str) -> list[AuditEvent]: ...

    def contains_event_id(self, event_id: str) -> bool: ...


@runtime_checkable
class IdempotencyStore(Protocol):
    """Read and save application idempotency records."""

    async def get(self, idempotency_key: str) -> IdempotencyRecord | None: ...

    async def save(self, record: IdempotencyRecord) -> None: ...
