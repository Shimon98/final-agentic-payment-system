"""Lifecycle and outbox tests for the copy-on-write Unit of Work."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentic_payments.application import ApplicationState
from agentic_payments.domain import AuditEvent, StateInvariantError, User
from agentic_payments.infrastructure.concurrency import (
    PaymentTransactionManager,
    PaymentUnitOfWork,
)

FIXED_TIME = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def _event(event_id: str = "AUD-1") -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        correlation_id="CORR-1",
        action="TEST",
        status="COMPLETED",
        occurred_at=FIXED_TIME,
        actor="test",
        details={"fixed": True},
    )


class FakeStateRepository:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.saved: list[ApplicationState] = []

    async def load(self) -> ApplicationState:
        return ApplicationState()

    async def save_atomic(self, state: ApplicationState) -> None:
        if self.fail:
            raise OSError("save failed")
        self.saved.append(state.clone())

    async def reset(self) -> None:
        self.saved.clear()


@pytest.mark.asyncio
async def test_working_state_is_independent_and_precommit_mutation_is_private() -> None:
    initial = ApplicationState()
    manager = PaymentTransactionManager(
        initial_state=initial,
        state_repository=FakeStateRepository(),
    )

    async with manager.transaction() as unit:
        unit.append_audit(_event())
        assert "AUD-1" in unit.state.pending_audit_events
        assert manager.current_state.pending_audit_events == {}
        assert initial.pending_audit_events == {}


@pytest.mark.asyncio
async def test_append_audit_stores_event_by_event_id() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(),
    )
    event = _event()

    async with manager.transaction() as unit:
        unit.append_audit(event)

        assert unit.state.pending_audit_events == {"AUD-1": event}


@pytest.mark.asyncio
async def test_append_audit_rejects_duplicate_event_id() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(),
    )

    async with manager.transaction() as unit:
        unit.append_audit(_event())
        with pytest.raises(ValueError, match="duplicate audit event ID"):
            unit.append_audit(_event())


@pytest.mark.asyncio
async def test_append_audit_rejects_non_event() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(),
    )

    async with manager.transaction() as unit:
        with pytest.raises(TypeError, match="AuditEvent"):
            unit.append_audit("not-an-event")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_invariant_validation_delegates_to_application_state() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(),
    )

    async with manager.transaction() as unit:
        user = User("U-1", "User", "1234567", FIXED_TIME)
        unit.state.users[user.user_id] = user

        with pytest.raises(StateInvariantError, match="missing wallet"):
            unit.validate_invariants()


@pytest.mark.asyncio
async def test_commit_succeeds_once_and_repeated_commit_is_rejected() -> None:
    repository = FakeStateRepository()
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=repository,
    )

    async with manager.transaction() as unit:
        unit.append_audit(_event())
        await unit.commit()

        with pytest.raises(RuntimeError, match="no longer active"):
            await unit.commit()

    assert len(repository.saved) == 1
    assert "AUD-1" in manager.current_state.pending_audit_events


@pytest.mark.asyncio
async def test_rollback_is_idempotent_and_commit_after_rollback_is_rejected() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(),
    )

    async with manager.transaction() as unit:
        await unit.rollback()
        await unit.rollback()

        with pytest.raises(RuntimeError, match="no longer active"):
            await unit.commit()


@pytest.mark.asyncio
async def test_rollback_after_commit_is_noop_and_does_not_undo_commit() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(),
    )

    async with manager.transaction() as unit:
        unit.append_audit(_event())
        await unit.commit()
        await unit.rollback()

    assert "AUD-1" in manager.current_state.pending_audit_events


@pytest.mark.asyncio
async def test_state_is_inaccessible_after_commit() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(),
    )

    async with manager.transaction() as unit:
        await unit.commit()

    with pytest.raises(RuntimeError, match="no longer active"):
        _ = unit.state


@pytest.mark.asyncio
async def test_state_is_inaccessible_after_rollback() -> None:
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=FakeStateRepository(),
    )

    async with manager.transaction() as unit:
        await unit.rollback()

    with pytest.raises(RuntimeError, match="no longer active"):
        _ = unit.state


@pytest.mark.asyncio
async def test_persistence_failure_leaves_manager_unchanged_and_unit_active() -> None:
    repository = FakeStateRepository(fail=True)
    manager = PaymentTransactionManager(
        initial_state=ApplicationState(),
        state_repository=repository,
    )

    async with manager.transaction() as unit:
        unit.append_audit(_event())
        with pytest.raises(OSError, match="save failed"):
            await unit.commit()

        assert "AUD-1" in unit.state.pending_audit_events
        assert manager.current_state.pending_audit_events == {}
        await unit.rollback()

    assert manager.current_state.pending_audit_events == {}


def test_direct_unit_of_work_construction_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="PaymentTransactionManager"):
        PaymentUnitOfWork()
