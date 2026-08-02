"""Atomic commit, rollback, and serialization tests for transaction management."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from agentic_payments.application import ApplicationState
from agentic_payments.domain import AuditEvent, StateInvariantError, User
from agentic_payments.infrastructure.concurrency import PaymentTransactionManager

FIXED_TIME = datetime(2026, 2, 3, 4, 5, tzinfo=UTC)


def _event(event_id: str) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        correlation_id=f"CORR-{event_id}",
        action="TEST",
        status="COMPLETED",
        occurred_at=FIXED_TIME,
        actor="test",
        details={"event": event_id},
    )


class FakeStateRepository:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.save_calls = 0
        self.received: list[ApplicationState] = []

    async def load(self) -> ApplicationState:
        return ApplicationState()

    async def save_atomic(self, state: ApplicationState) -> None:
        self.save_calls += 1
        self.received.append(state)
        if self.fail:
            raise OSError("configured failure")

    async def reset(self) -> None:
        self.received.clear()


def test_constructor_validates_initial_state() -> None:
    user = User("U-1", "User", "1234567", FIXED_TIME)
    invalid = ApplicationState(users={user.user_id: user})

    with pytest.raises(StateInvariantError, match="missing wallet"):
        PaymentTransactionManager(
            initial_state=invalid,
            state_repository=FakeStateRepository(),
        )


def test_constructor_rejects_non_application_state() -> None:
    with pytest.raises(TypeError, match="ApplicationState"):
        PaymentTransactionManager(
            initial_state="invalid",  # type: ignore[arg-type]
            state_repository=FakeStateRepository(),
        )


def test_constructor_clones_input_and_current_state_returns_clone() -> None:
    initial = ApplicationState()
    manager = PaymentTransactionManager(
        initial_state=initial,
        state_repository=FakeStateRepository(),
    )

    initial.pending_audit_events["LATE"] = _event("LATE")
    first = manager.current_state
    first.pending_audit_events["LOCAL"] = _event("LOCAL")

    assert manager.current_state.pending_audit_events == {}


@pytest.mark.asyncio
async def test_normal_exit_without_commit_rolls_back() -> None:
    repository = FakeStateRepository()
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=repository,
    )

    async with manager.transaction() as unit:
        unit.append_audit(_event("AUD-1"))

    assert repository.save_calls == 0
    assert manager.current_state.pending_audit_events == {}


@pytest.mark.asyncio
async def test_caller_exception_rolls_back_and_reraises_original() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(),
    )

    with pytest.raises(LookupError, match="caller failed"):
        async with manager.transaction() as unit:
            unit.append_audit(_event("AUD-1"))
            raise LookupError("caller failed")

    assert manager.current_state.pending_audit_events == {}


@pytest.mark.asyncio
async def test_explicit_commit_replaces_current_state() -> None:
    repository = FakeStateRepository()
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=repository,
    )

    async with manager.transaction() as unit:
        unit.append_audit(_event("AUD-1"))
        await unit.commit()

    assert set(manager.current_state.pending_audit_events) == {"AUD-1"}
    assert repository.save_calls == 1


@pytest.mark.asyncio
async def test_repository_and_manager_receive_separate_clones() -> None:
    repository = FakeStateRepository()
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=repository,
    )

    async with manager.transaction() as unit:
        working = unit.state
        unit.append_audit(_event("AUD-1"))
        await unit.commit()

    repository.received[0].pending_audit_events["REPO"] = _event("REPO")
    working.pending_audit_events["WORKING"] = _event("WORKING")

    assert set(manager.current_state.pending_audit_events) == {"AUD-1"}


@pytest.mark.asyncio
async def test_concurrent_transactions_are_serialized() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(),
    )
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first() -> None:
        async with manager.transaction():
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        await first_entered.wait()
        async with manager.transaction():
            second_entered.set()

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await first_entered.wait()
    await asyncio.sleep(0)
    assert not second_entered.is_set()

    release_first.set()
    await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=1.0)
    assert second_entered.is_set()


@pytest.mark.asyncio
async def test_disjoint_concurrent_updates_do_not_overwrite_from_stale_snapshots() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(),
    )
    start = asyncio.Event()

    async def add(event_id: str) -> None:
        await start.wait()
        async with manager.transaction() as unit:
            unit.append_audit(_event(event_id))
            await unit.commit()

    tasks = [
        asyncio.create_task(add("AUD-A")),
        asyncio.create_task(add("AUD-B")),
    ]
    start.set()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)

    assert set(manager.current_state.pending_audit_events) == {"AUD-A", "AUD-B"}


@pytest.mark.asyncio
async def test_failed_repository_save_does_not_swap_state_and_gate_releases() -> None:
    repository = FakeStateRepository(fail=True)
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=repository,
    )

    with pytest.raises(OSError, match="configured failure"):
        async with manager.transaction() as unit:
            unit.append_audit(_event("FAILED"))
            await unit.commit()

    assert manager.current_state.pending_audit_events == {}

    repository.fail = False
    async with asyncio.timeout(1.0):
        async with manager.transaction() as unit:
            unit.append_audit(_event("RECOVERED"))
            await unit.commit()

    assert set(manager.current_state.pending_audit_events) == {"RECOVERED"}


@pytest.mark.asyncio
async def test_business_change_and_audit_event_commit_together() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(),
    )

    async with manager.transaction() as unit:
        unit.state.memory = unit.state.memory
        unit.append_audit(_event("OUTBOX"))
        await unit.commit()

    committed = manager.current_state
    assert "OUTBOX" in committed.pending_audit_events


@pytest.mark.asyncio
async def test_failed_save_commits_neither_working_change_nor_outbox_event() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(fail=True),
    )

    with pytest.raises(OSError):
        async with manager.transaction() as unit:
            unit.append_audit(_event("OUTBOX"))
            await unit.commit()

    assert manager.current_state.pending_audit_events == {}


@pytest.mark.asyncio
async def test_manager_does_not_deliver_or_remove_pending_event() -> None:
    repository = FakeStateRepository()
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=repository,
    )

    async with manager.transaction() as unit:
        unit.append_audit(_event("PENDING"))
        await unit.commit()

    assert set(repository.received[0].pending_audit_events) == {"PENDING"}
    assert set(manager.current_state.pending_audit_events) == {"PENDING"}
