"""Restart persistence through the production composition root."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_payments.bootstrap import build_application
from agentic_payments.infrastructure import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        state_file=tmp_path / "state.json",
        audit_file=tmp_path / "audit.jsonl",
    )


@pytest.mark.asyncio
async def test_restart_loads_users_transaction_memory_and_explanation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = await build_application(settings)
    alice = await first.orchestrator.handle(
        'createUser name="Alice" phone=0501111111 initial_balance=1000.00',
        idempotency_key="RESTART-ALICE",
    )
    bob = await first.orchestrator.handle(
        'createUser name="Bob" phone=0502222222 initial_balance=100.00',
        idempotency_key="RESTART-BOB",
    )
    alice_id = alice.output["user_id"]
    bob_id = bob.output["user_id"]
    transfer = await first.orchestrator.handle(
        f"transferMoney sender_id={alice_id} receiver_id={bob_id} amount=40.00",
        idempotency_key="RESTART-TRANSFER",
    )

    second = await build_application(settings)
    balance = await second.orchestrator.handle(f"checkBalance user_id={alice_id}")
    explanation = await second.orchestrator.handle("explainLastAction")

    state = second.snapshot()
    assert len(state.users) == 2
    assert transfer.output["transaction_id"] in state.transactions
    assert state.memory.last_transaction_id == transfer.output["transaction_id"]
    assert second.memory_service.snapshot().last_transaction_id == transfer.output["transaction_id"]
    assert balance.output["balance"] == "960.00"
    assert explanation.output["facts"]
