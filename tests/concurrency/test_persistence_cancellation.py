"""Real thread-write cancellation tests for disk/index/memory consistency."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentic_payments.application import ApplicationState
from agentic_payments.domain import AuditEvent
from agentic_payments.infrastructure import (
    AuditPersistenceError,
    JsonLinesAuditRepository,
    JsonStateRepository,
    StatePersistenceError,
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
async def test_cancel_during_successful_state_write_keeps_disk_and_memory_consistent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = JsonStateRepository(tmp_path / "state.json")
    await repository.save_atomic(ApplicationState())
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=repository,
    )
    original_write = repository._write_sync
    entered = threading.Event()
    release = threading.Event()

    def controlled_write(payload: str) -> None:
        entered.set()
        assert release.wait(timeout=2.0)
        original_write(payload)

    monkeypatch.setattr(repository, "_write_sync", controlled_write)

    async def commit() -> None:
        async with manager.transaction() as unit:
            unit.append_audit(_event("AUD-CANCELLED"))
            await unit.commit()

    task = asyncio.create_task(commit())
    assert await asyncio.to_thread(entered.wait, 1.0)
    task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)

    assert set(manager.current_state.pending_audit_events) == {"AUD-CANCELLED"}
    assert set((await repository.load()).pending_audit_events) == {"AUD-CANCELLED"}

    async with asyncio.timeout(1.0):
        async with manager.transaction() as unit:
            unit.append_audit(_event("AUD-REUSED"))
            await unit.commit()
    assert set(manager.current_state.pending_audit_events) == {
        "AUD-CANCELLED",
        "AUD-REUSED",
    }


@pytest.mark.asyncio
async def test_cancel_during_failed_state_write_retains_old_disk_and_memory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = JsonStateRepository(tmp_path / "state.json")
    await repository.save_atomic(ApplicationState())
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=repository,
    )
    entered = threading.Event()
    release = threading.Event()

    def controlled_failure(payload: str) -> None:
        entered.set()
        assert release.wait(timeout=2.0)
        raise OSError("controlled failed write")

    monkeypatch.setattr(repository, "_write_sync", controlled_failure)

    async def commit() -> None:
        async with manager.transaction() as unit:
            unit.append_audit(_event("AUD-FAILED"))
            await unit.commit()

    task = asyncio.create_task(commit())
    assert await asyncio.to_thread(entered.wait, 1.0)
    task.cancel()
    release.set()

    with pytest.raises(StatePersistenceError) as caught:
        await asyncio.wait_for(task, timeout=2.0)

    assert isinstance(caught.value.__cause__, OSError)
    assert manager.current_state.pending_audit_events == {}
    assert (await repository.load()).pending_audit_events == {}


@pytest.mark.asyncio
async def test_cancel_during_successful_audit_append_updates_index_and_retry_is_noop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "audit.jsonl"
    repository = JsonLinesAuditRepository(path)
    await repository.initialize()
    original_append = repository._append_sync
    entered = threading.Event()
    release = threading.Event()

    def controlled_append(line: str) -> None:
        entered.set()
        assert release.wait(timeout=2.0)
        original_append(line)

    monkeypatch.setattr(repository, "_append_sync", controlled_append)
    event = _event("AUD-CANCELLED")
    task = asyncio.create_task(repository.append(event))
    assert await asyncio.to_thread(entered.wait, 1.0)
    task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)

    first_payload = path.read_bytes()
    assert repository.contains_event_id(event.event_id)
    assert await repository.list_all() == [event]
    await repository.append(event)
    assert path.read_bytes() == first_payload

    await repository.append(_event("AUD-REUSED"))
    assert len(await repository.list_all()) == 2


@pytest.mark.asyncio
async def test_cancel_during_failed_audit_append_keeps_index_consistent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = JsonLinesAuditRepository(tmp_path / "audit.jsonl")
    await repository.initialize()
    entered = threading.Event()
    release = threading.Event()

    def controlled_failure(line: str) -> None:
        entered.set()
        assert release.wait(timeout=2.0)
        raise OSError("controlled failed append")

    monkeypatch.setattr(repository, "_append_sync", controlled_failure)
    event = _event("AUD-FAILED")
    task = asyncio.create_task(repository.append(event))
    assert await asyncio.to_thread(entered.wait, 1.0)
    task.cancel()
    release.set()

    with pytest.raises(AuditPersistenceError) as caught:
        await asyncio.wait_for(task, timeout=2.0)

    assert isinstance(caught.value.__cause__, OSError)
    assert not repository.contains_event_id(event.event_id)
