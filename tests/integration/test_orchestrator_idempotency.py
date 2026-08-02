"""Orchestrator idempotency replay and conflict tests."""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.test_orchestrator_business_flows import (
    NOW,
    build_system,
    create_users,
)


@pytest.mark.asyncio
async def test_same_mutation_key_replays_one_transaction(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    first, second = await create_users(system)
    command = f"transferMoney sender_id={first} receiver_id={second} amount=10.00"

    one = await system.orchestrator.handle(
        command,
        idempotency_key="IDEMP-SAME",
        requested_at=NOW,
    )
    two = await system.orchestrator.handle(
        command,
        idempotency_key="IDEMP-SAME",
        requested_at=NOW,
    )

    assert one.output["transaction_id"] == two.output["transaction_id"]
    assert len(system.payment.manager.current_state.transactions) == 1


@pytest.mark.asyncio
async def test_same_key_changed_parameters_is_reflected_conflict(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    first, second = await create_users(system)
    await system.orchestrator.handle(
        f"transferMoney sender_id={first} receiver_id={second} amount=10.00",
        idempotency_key="IDEMP-CONFLICT",
        requested_at=NOW,
    )

    conflict = await system.orchestrator.handle(
        f"transferMoney sender_id={first} receiver_id={second} amount=11.00",
        idempotency_key="IDEMP-CONFLICT",
        requested_at=NOW,
    )

    assert conflict.agent_name == "ReflectionAgent"
    assert conflict.output.error_code == "idempotency_conflict"
    assert len(system.payment.manager.current_state.transactions) == 1
