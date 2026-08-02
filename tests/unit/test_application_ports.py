"""Tests for runtime-checkable application protocols."""

from __future__ import annotations

from datetime import UTC, datetime

from agentic_payments.application import (
    ApplicationState,
    AuditRepository,
    Clock,
    IdempotencyRecord,
    IdempotencyStore,
    IdGenerator,
    StateRepository,
)
from agentic_payments.domain import AuditEvent


class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 1, tzinfo=UTC)


class FakeIds:
    def new_user_id(self) -> str:
        return "USR"

    def new_transaction_id(self) -> str:
        return "TXN"

    def new_payment_request_id(self) -> str:
        return "REQ"

    def new_audit_event_id(self) -> str:
        return "EVT"

    def new_correlation_id(self) -> str:
        return "COR"


class FakeStateRepository:
    async def load(self) -> ApplicationState:
        return ApplicationState()

    async def save_atomic(self, state: ApplicationState) -> None:
        return None

    async def reset(self) -> None:
        return None


class FakeAuditRepository:
    async def append(self, event: AuditEvent) -> None:
        return None

    async def list_all(self) -> list[AuditEvent]:
        return []

    async def find_by_correlation_id(self, correlation_id: str) -> list[AuditEvent]:
        return []

    def contains_event_id(self, event_id: str) -> bool:
        return False


class FakeIdempotencyStore:
    async def get(self, idempotency_key: str) -> IdempotencyRecord | None:
        return None

    async def save(self, record: IdempotencyRecord) -> None:
        return None


class Incomplete:
    pass


def test_application_port_runtime_protocols_accept_complete_fakes() -> None:
    assert isinstance(FakeClock(), Clock)
    assert isinstance(FakeIds(), IdGenerator)
    assert isinstance(FakeStateRepository(), StateRepository)
    assert isinstance(FakeAuditRepository(), AuditRepository)
    assert isinstance(FakeIdempotencyStore(), IdempotencyStore)


def test_application_port_runtime_protocols_reject_incomplete_fakes() -> None:
    incomplete = Incomplete()
    assert not isinstance(incomplete, Clock)
    assert not isinstance(incomplete, IdGenerator)
    assert not isinstance(incomplete, StateRepository)
    assert not isinstance(incomplete, AuditRepository)
    assert not isinstance(incomplete, IdempotencyStore)


def test_application_port_protocol_methods_exist() -> None:
    assert {"now"} <= set(Clock.__dict__)
    assert {"new_user_id", "new_transaction_id", "new_payment_request_id"} <= set(
        IdGenerator.__dict__
    )
    assert {"load", "save_atomic", "reset"} <= set(StateRepository.__dict__)
    assert {"append", "list_all", "find_by_correlation_id", "contains_event_id"} <= set(
        AuditRepository.__dict__
    )
    assert {"get", "save"} <= set(IdempotencyStore.__dict__)
