"""Single-instance serialization tests for JSON state persistence."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentic_payments.application import ApplicationState
from agentic_payments.domain import AuditEvent
from agentic_payments.infrastructure import JsonStateRepository, StatePersistenceError

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
async def test_concurrent_saves_on_one_instance_are_serialized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = JsonStateRepository(tmp_path / "state.json")
    original_write = repository._write_sync
    first_entered = threading.Event()
    release_first = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def controlled_write(payload: str) -> None:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_entered.set()
            assert release_first.wait(timeout=2.0)
        original_write(payload)

    monkeypatch.setattr(repository, "_write_sync", controlled_write)
    first = asyncio.create_task(
        repository.save_atomic(ApplicationState(pending_audit_events={"AUD-A": _event("AUD-A")}))
    )
    assert await asyncio.to_thread(first_entered.wait, 1.0)
    second = asyncio.create_task(
        repository.save_atomic(ApplicationState(pending_audit_events={"AUD-B": _event("AUD-B")}))
    )
    await asyncio.sleep(0)
    with calls_lock:
        assert calls == 1

    release_first.set()
    await asyncio.wait_for(asyncio.gather(first, second), timeout=2.0)

    assert set((await repository.load()).pending_audit_events) == {"AUD-B"}


@pytest.mark.asyncio
async def test_concurrent_load_save_never_exposes_partial_json(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    repository = JsonStateRepository(path)
    await repository.save_atomic(ApplicationState())
    states = [
        ApplicationState(pending_audit_events={f"AUD-{index}": _event(f"AUD-{index}")})
        for index in range(20)
    ]

    async def save_and_parse(state: ApplicationState) -> None:
        await repository.save_atomic(state)
        loaded = await repository.load()
        loaded.validate_invariants()
        json.loads(path.read_text(encoding="utf-8"))

    await asyncio.wait_for(
        asyncio.gather(*(save_and_parse(state) for state in states)),
        timeout=5.0,
    )

    (await repository.load()).validate_invariants()


@pytest.mark.asyncio
async def test_state_is_snapshotted_before_thread_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = JsonStateRepository(tmp_path / "state.json")
    original_write = repository._write_sync
    entered = threading.Event()
    release = threading.Event()

    def controlled_write(payload: str) -> None:
        entered.set()
        assert release.wait(timeout=2.0)
        original_write(payload)

    monkeypatch.setattr(repository, "_write_sync", controlled_write)
    state = ApplicationState(pending_audit_events={"AUD-1": _event("AUD-1")})
    task = asyncio.create_task(repository.save_atomic(state))
    assert await asyncio.to_thread(entered.wait, 1.0)

    state.pending_audit_events.clear()
    release.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert set((await repository.load()).pending_audit_events) == {"AUD-1"}


@pytest.mark.asyncio
async def test_repository_lock_is_reusable_after_controlled_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = JsonStateRepository(tmp_path / "state.json")
    original_write = repository._write_sync
    fail = True

    def fail_once(payload: str) -> None:
        nonlocal fail
        if fail:
            fail = False
            raise OSError("controlled failure")
        original_write(payload)

    monkeypatch.setattr(repository, "_write_sync", fail_once)
    with pytest.raises(StatePersistenceError):
        await repository.save_atomic(ApplicationState())

    await asyncio.wait_for(repository.save_atomic(ApplicationState()), timeout=1.0)
