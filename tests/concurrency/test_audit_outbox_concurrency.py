"""Serialization tests for concurrent outbox flush calls."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentic_payments.application import ApplicationState
from agentic_payments.domain import AuditEvent
from agentic_payments.infrastructure import (
    AuditOutboxDispatcher,
    JsonLinesAuditRepository,
    JsonStateRepository,
)
from agentic_payments.infrastructure.concurrency import PaymentTransactionManager

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _event(event_id: str) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        correlation_id=f"COR-{event_id}",
        action="TEST",
        status="SUCCESS",
        occurred_at=NOW,
        actor="system",
        details={},
    )


@pytest.mark.asyncio
async def test_concurrent_flushes_on_one_dispatcher_are_serialized(
    tmp_path: Path,
) -> None:
    events = {_event(f"AUD-{index}").event_id: _event(f"AUD-{index}") for index in range(10)}
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(pending_audit_events=events),
        state_repository=JsonStateRepository(tmp_path / "state.json"),
    )
    audit = JsonLinesAuditRepository(tmp_path / "audit.jsonl")
    dispatcher = AuditOutboxDispatcher(
        transaction_manager=manager,
        audit_repository=audit,
    )

    first, second = await asyncio.wait_for(
        asyncio.gather(dispatcher.flush_pending(), dispatcher.flush_pending()),
        timeout=5.0,
    )

    assert sorted((first.attempted, second.attempted)) == [0, 10]
    assert first.removed + second.removed == 10
    assert len(await audit.list_all()) == 10
    assert manager.current_state.pending_audit_events == {}


@pytest.mark.asyncio
async def test_dispatcher_lock_is_reusable_after_cancellation(tmp_path: Path) -> None:
    event = _event("AUD-1")
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(pending_audit_events={event.event_id: event}),
        state_repository=JsonStateRepository(tmp_path / "state.json"),
    )
    audit = JsonLinesAuditRepository(tmp_path / "audit.jsonl")
    dispatcher = AuditOutboxDispatcher(
        transaction_manager=manager,
        audit_repository=audit,
    )
    await audit.initialize()
    held = await dispatcher._flush_lock.__aenter__()
    assert held is None
    waiting = asyncio.create_task(dispatcher.flush_pending())
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await dispatcher._flush_lock.__aexit__(None, None, None)

    result = await asyncio.wait_for(dispatcher.flush_pending(), timeout=2.0)
    assert result.removed == 1
