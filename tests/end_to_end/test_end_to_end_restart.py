"""Durable state and business-memory restart scenario."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentic_payments.infrastructure import JsonStateRepository
from tests.integration.test_orchestrator_business_flows import (
    NOW,
    build_system,
    create_users,
)


@pytest.mark.asyncio
async def test_users_transactions_and_memory_survive_new_orchestrator(
    payment_harness_factory: Any,
    tmp_path: Path,
) -> None:
    repository = JsonStateRepository(tmp_path / "state.json")
    initial = await repository.load()
    first_system = build_system(
        payment_harness_factory,
        initial_state=initial,
        repository=repository,
    )
    first, second = await create_users(first_system)
    transfer = await first_system.orchestrator.handle(
        f"transferMoney sender_id={first} receiver_id={second} amount=40.00",
        idempotency_key="IDEMP-RESTART-T",
        requested_at=NOW,
    )

    loaded = await repository.load()
    restarted = build_system(
        payment_harness_factory,
        initial_state=loaded,
        repository=repository,
    )
    balance = await restarted.orchestrator.handle(
        f"checkBalance user_id={first}",
        requested_at=NOW,
    )
    explanation = await restarted.orchestrator.handle(
        "explainLastAction",
        requested_at=NOW,
    )

    assert balance.output["balance"] == "960.00"
    assert transfer.output["transaction_id"] in restarted.payment.manager.current_state.transactions
    assert restarted.memory.snapshot().last_transaction_id == transfer.output["transaction_id"]
    assert explanation.agent_name == "OrchestratorAgent"
    assert explanation.output["facts"]
