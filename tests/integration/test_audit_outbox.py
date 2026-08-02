"""Integration tests for durable, retry-safe transactional outbox delivery."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentic_payments.application import ApplicationState
from agentic_payments.domain import AuditEvent
from agentic_payments.infrastructure import (
    AuditOutboxDispatcher,
    AuditPersistenceError,
    JsonLinesAuditRepository,
    JsonStateRepository,
    OutboxFailure,
    OutboxFlushResult,
)
from agentic_payments.infrastructure.concurrency import PaymentTransactionManager

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _event(
    event_id: str,
    *,
    occurred_at: datetime = NOW,
    label: str = "original",
) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        correlation_id=f"COR-{event_id}",
        action="TEST",
        status="SUCCESS",
        occurred_at=occurred_at,
        actor="system",
        details={"label": label},
    )


def _manager(
    state: ApplicationState,
    repository: object,
) -> PaymentTransactionManager:
    return PaymentTransactionManager(
        initial_state=state,
        state_repository=repository,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_empty_flush_has_exact_counts(tmp_path: Path) -> None:
    manager = _manager(ApplicationState(), JsonStateRepository(tmp_path / "state.json"))
    dispatcher = AuditOutboxDispatcher(
        transaction_manager=manager,
        audit_repository=JsonLinesAuditRepository(tmp_path / "audit.jsonl"),
    )

    result = await dispatcher.flush_pending()

    assert result == OutboxFlushResult(0, 0, 0, 0, (), 0)


@pytest.mark.asyncio
async def test_successful_delivery_removes_events_in_deterministic_order(
    tmp_path: Path,
) -> None:
    early_b = _event("AUD-B", occurred_at=NOW)
    early_a = _event("AUD-A", occurred_at=NOW)
    late = _event("AUD-C", occurred_at=NOW + timedelta(seconds=1))
    state = ApplicationState(
        pending_audit_events={
            late.event_id: late,
            early_b.event_id: early_b,
            early_a.event_id: early_a,
        }
    )
    manager = _manager(state, JsonStateRepository(tmp_path / "state.json"))
    audit = JsonLinesAuditRepository(tmp_path / "audit.jsonl")

    result = await AuditOutboxDispatcher(
        transaction_manager=manager,
        audit_repository=audit,
    ).flush_pending()

    assert result == OutboxFlushResult(3, 3, 0, 3, (), 0)
    assert await audit.list_all() == [early_a, early_b, late]
    assert manager.current_state.pending_audit_events == {}


@pytest.mark.asyncio
async def test_already_delivered_event_is_removed_without_duplicate(
    tmp_path: Path,
) -> None:
    event = _event("AUD-1")
    audit_path = tmp_path / "audit.jsonl"
    audit = JsonLinesAuditRepository(audit_path)
    await audit.append(event)
    original = audit_path.read_bytes()
    manager = _manager(
        ApplicationState(pending_audit_events={event.event_id: event}),
        JsonStateRepository(tmp_path / "state.json"),
    )

    result = await AuditOutboxDispatcher(
        transaction_manager=manager,
        audit_repository=audit,
    ).flush_pending()

    assert result == OutboxFlushResult(1, 0, 1, 1, (), 0)
    assert audit_path.read_bytes() == original


class _FailingAuditRepository:
    def __init__(self, fail_ids: set[str]) -> None:
        self.fail_ids = fail_ids
        self.events: dict[str, AuditEvent] = {}
        self.order: list[str] = []

    async def append(self, event: AuditEvent) -> None:
        if event.event_id in self.fail_ids:
            raise AuditPersistenceError("Configured audit append failure")
        self.events[event.event_id] = event
        self.order.append(event.event_id)

    async def list_all(self) -> list[AuditEvent]:
        return [self.events[event_id] for event_id in self.order]

    async def find_by_correlation_id(self, correlation_id: str) -> list[AuditEvent]:
        return [event for event in await self.list_all() if event.correlation_id == correlation_id]

    def contains_event_id(self, event_id: str) -> bool:
        return event_id in self.events


@pytest.mark.asyncio
async def test_append_failure_leaves_pending_and_later_events_continue(
    tmp_path: Path,
) -> None:
    failed = _event("AUD-A")
    delivered = _event("AUD-B", occurred_at=NOW + timedelta(seconds=1))
    state = ApplicationState(
        pending_audit_events={
            failed.event_id: failed,
            delivered.event_id: delivered,
        }
    )
    manager = _manager(state, JsonStateRepository(tmp_path / "state.json"))
    audit = _FailingAuditRepository({"AUD-A"})

    result = await AuditOutboxDispatcher(
        transaction_manager=manager,
        audit_repository=audit,
    ).flush_pending()

    assert result.attempted == 2
    assert result.delivered == 1
    assert result.removed == 1
    assert result.pending_after == 1
    assert result.failures == (
        OutboxFailure(
            event_id="AUD-A",
            error_type="AuditPersistenceError",
            message="Configured audit append failure",
        ),
    )
    assert set(manager.current_state.pending_audit_events) == {"AUD-A"}


class _FailOnceStateRepository:
    def __init__(self) -> None:
        self.fail = True
        self.saved: list[ApplicationState] = []

    async def load(self) -> ApplicationState:
        return self.saved[-1].clone() if self.saved else ApplicationState()

    async def save_atomic(self, state: ApplicationState) -> None:
        if self.fail:
            raise OSError("configured removal failure")
        self.saved.append(state.clone())

    async def reset(self) -> None:
        self.saved.clear()


@pytest.mark.asyncio
async def test_removal_failure_retries_without_duplicate_audit_line(tmp_path: Path) -> None:
    event = _event("AUD-1")
    state_repository = _FailOnceStateRepository()
    manager = _manager(
        ApplicationState(pending_audit_events={event.event_id: event}),
        state_repository,
    )
    audit_path = tmp_path / "audit.jsonl"
    audit = JsonLinesAuditRepository(audit_path)
    dispatcher = AuditOutboxDispatcher(
        transaction_manager=manager,
        audit_repository=audit,
    )

    first = await dispatcher.flush_pending()
    first_payload = audit_path.read_bytes()
    state_repository.fail = False
    second = await dispatcher.flush_pending()

    assert first.delivered == 0
    assert first.removed == 0
    assert first.pending_after == 1
    assert len(first.failures) == 1
    assert second == OutboxFlushResult(1, 0, 1, 1, (), 0)
    assert audit_path.read_bytes() == first_payload
    assert len(await audit.list_all()) == 1


class _MutatingAuditRepository(_FailingAuditRepository):
    def __init__(self) -> None:
        super().__init__(set())
        self.manager: PaymentTransactionManager | None = None

    async def append(self, event: AuditEvent) -> None:
        await super().append(event)
        assert self.manager is not None
        async with self.manager.transaction() as unit:
            unit.state.pending_audit_events[event.event_id] = _event(
                event.event_id,
                label="different",
            )
            await unit.commit()


@pytest.mark.asyncio
async def test_same_id_different_pending_content_fails_safely(tmp_path: Path) -> None:
    event = _event("AUD-1")
    manager = _manager(
        ApplicationState(pending_audit_events={event.event_id: event}),
        JsonStateRepository(tmp_path / "state.json"),
    )
    audit = _MutatingAuditRepository()
    audit.manager = manager

    result = await AuditOutboxDispatcher(
        transaction_manager=manager,
        audit_repository=audit,
    ).flush_pending()

    assert result.removed == 0
    assert result.pending_after == 1
    assert result.failures[0].error_type == "StatePersistenceError"
    assert manager.current_state.pending_audit_events["AUD-1"].details["label"] == "different"


class _CancelledAuditRepository(_FailingAuditRepository):
    async def append(self, event: AuditEvent) -> None:
        raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_cancellation_propagates_and_event_is_not_removed(tmp_path: Path) -> None:
    event = _event("AUD-1")
    manager = _manager(
        ApplicationState(pending_audit_events={event.event_id: event}),
        JsonStateRepository(tmp_path / "state.json"),
    )

    with pytest.raises(asyncio.CancelledError):
        await AuditOutboxDispatcher(
            transaction_manager=manager,
            audit_repository=_CancelledAuditRepository(set()),
        ).flush_pending()

    assert "AUD-1" in manager.current_state.pending_audit_events


@pytest.mark.asyncio
async def test_pending_event_survives_restart_and_is_delivered(tmp_path: Path) -> None:
    event = _event("AUD-RESTART")
    state_path = tmp_path / "state.json"
    state_repository = JsonStateRepository(state_path)
    await state_repository.save_atomic(
        ApplicationState(pending_audit_events={event.event_id: event})
    )

    restarted_repository = JsonStateRepository(state_path)
    restarted_manager = _manager(await restarted_repository.load(), restarted_repository)
    audit = JsonLinesAuditRepository(tmp_path / "audit.jsonl")
    result = await AuditOutboxDispatcher(
        transaction_manager=restarted_manager,
        audit_repository=audit,
    ).flush_pending()

    assert result == OutboxFlushResult(1, 1, 0, 1, (), 0)
    assert await audit.list_all() == [event]


def test_outbox_result_types_validate_exact_runtime_contract() -> None:
    with pytest.raises(TypeError):
        OutboxFlushResult(True, 0, 0, 0, (), 0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OutboxFlushResult(0, 0, 0, 1, (), 0)
    with pytest.raises(TypeError):
        OutboxFlushResult(0, 0, 0, 0, [], 0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OutboxFailure(" ", "Error", "message")
