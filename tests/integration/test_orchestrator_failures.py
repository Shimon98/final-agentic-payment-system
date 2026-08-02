"""Reflection, fallback, and pre-commit failure integration tests."""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.test_orchestrator_business_flows import (
    NOW,
    build_system,
    create_users,
)


@pytest.mark.asyncio
async def test_negative_insufficient_missing_receiver_and_self_transfer_reflect(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    first, second = await create_users(system)
    commands = (
        f"transferMoney sender_id={first} receiver_id={second} amount=-1.00",
        f"transferMoney sender_id={first} receiver_id={second} amount=2000.00",
        f"transferMoney sender_id={first} receiver_id=MISSING amount=1.00",
        f"transferMoney sender_id={first} receiver_id={first} amount=1.00",
    )

    results = [
        await system.orchestrator.handle(
            command,
            idempotency_key=f"IDEMP-ERR-{index}",
            requested_at=NOW,
        )
        for index, command in enumerate(commands)
    ]

    assert all(result.agent_name == "ReflectionAgent" for result in results)
    assert all(result.metadata["error_handled"] is True for result in results)
    assert system.payment.manager.current_state.wallets[first].balance == 1000


@pytest.mark.asyncio
async def test_unknown_and_missing_parameters_never_mutate(
    payment_harness_factory: Any,
) -> None:
    system = build_system(payment_harness_factory)
    before = system.payment.manager.current_state.to_dict()

    unknown = await system.orchestrator.handle("sing a song", requested_at=NOW)
    missing = await system.orchestrator.handle(
        "transferMoney sender_id=U1",
        requested_at=NOW,
    )

    after = system.payment.manager.current_state.to_dict()
    assert unknown.agent_name == missing.agent_name == "FallbackAgent"
    assert before["users"] == after["users"]
    assert before["wallets"] == after["wallets"]
    assert before["transactions"] == after["transactions"]
