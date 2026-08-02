"""Transactional safe-reset integration tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from agentic_payments.application import BusinessMemory
from agentic_payments.bootstrap import ApplicationContainer, build_application
from agentic_payments.infrastructure import OutboxFlushResult, Settings, StatePersistenceError


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        state_file=tmp_path / "state.json",
        audit_file=tmp_path / "audit.jsonl",
    )


async def _populate(container: ApplicationContainer) -> tuple[str, str]:
    alice = await container.orchestrator.handle(
        'createUser name="Alice" phone=0501111111 initial_balance=1000.00',
        idempotency_key="RESET-ALICE",
    )
    bob = await container.orchestrator.handle(
        'createUser name="Bob" phone=0502222222 initial_balance=100.00',
        idempotency_key="RESET-BOB",
    )
    alice_id = alice.output["user_id"]
    bob_id = bob.output["user_id"]
    await container.orchestrator.handle(
        f"transferMoney sender_id={alice_id} receiver_id={bob_id} amount=20.00",
        idempotency_key="RESET-TRANSFER",
    )
    await container.orchestrator.handle(
        f"requestPayment requester_id={bob_id} payer_id={alice_id} amount=5.00",
        idempotency_key="RESET-REQUEST",
    )
    return alice_id, bob_id


@pytest.mark.asyncio
async def test_successful_reset_clears_business_state_but_preserves_audit(tmp_path: Path) -> None:
    container = await build_application(_settings(tmp_path))
    await _populate(container)
    audit_before = container.settings.audit_file.read_bytes()

    result = await container.reset_state()

    state = container.snapshot()
    assert result.pending_after == 0
    assert state.users == {}
    assert state.wallets == {}
    assert state.transactions == {}
    assert state.payment_requests == {}
    assert state.idempotency_records == {}
    assert state.pending_audit_events == {}
    assert state.memory == BusinessMemory()
    assert container.memory_service.snapshot() == BusinessMemory()
    assert container.settings.audit_file.read_bytes() == audit_before


class _PendingOutbox:
    async def flush_pending(self) -> OutboxFlushResult:
        return OutboxFlushResult(1, 0, 0, 0, (), 1)


@pytest.mark.asyncio
async def test_reset_refuses_when_pending_delivery_remains(tmp_path: Path) -> None:
    container = await build_application(_settings(tmp_path))
    await _populate(container)
    before = container.snapshot()
    container.outbox_dispatcher = cast(Any, _PendingOutbox())

    with pytest.raises(
        StatePersistenceError,
        match="Cannot reset while audit events remain pending",
    ):
        await container.reset_state()

    assert container.snapshot() == before


@pytest.mark.asyncio
async def test_failed_reset_commit_preserves_state_and_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = await build_application(_settings(tmp_path))
    await _populate(container)
    state_before = container.snapshot()
    memory_before = container.memory_service.snapshot()

    async def fail_save(state: object) -> None:
        raise StatePersistenceError("Configured save failure")

    monkeypatch.setattr(container.state_repository, "save_atomic", fail_save)

    with pytest.raises(StatePersistenceError):
        await container.reset_state()

    assert container.snapshot() == state_before
    assert container.memory_service.snapshot() == memory_before


@pytest.mark.asyncio
async def test_reset_uses_one_unit_of_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = await build_application(_settings(tmp_path))
    original = container.transaction_manager.transaction
    calls = 0

    def counted_transaction() -> object:
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(container.transaction_manager, "transaction", counted_transaction)

    await container.reset_state()

    assert calls == 1
