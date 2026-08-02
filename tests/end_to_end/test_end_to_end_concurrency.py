"""Concurrent end-to-end requests through OrchestratorAgent.handle."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from tests.integration.test_orchestrator_business_flows import (
    NOW,
    build_system,
)


@pytest.mark.asyncio
async def test_double_spending_allows_one_transfer_and_final_balance_twenty(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    system = build_system(
        payment_harness_factory,
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "R1": Decimal("0.00"), "R2": Decimal("0.00")}
        ),
    )
    results = await asyncio.wait_for(
        asyncio.gather(
            system.orchestrator.handle(
                "transferMoney sender_id=SENDER receiver_id=R1 amount=80.00",
                idempotency_key="IDEMP-DS-1",
                requested_at=NOW,
            ),
            system.orchestrator.handle(
                "transferMoney sender_id=SENDER receiver_id=R2 amount=80.00",
                idempotency_key="IDEMP-DS-2",
                requested_at=NOW,
            ),
        ),
        timeout=2.0,
    )

    assert sorted(result.agent_name for result in results) == [
        "OrchestratorAgent",
        "ReflectionAgent",
    ]
    assert system.payment.manager.current_state.wallets["SENDER"].balance == Decimal("20.00")
    assert len(system.payment.manager.current_state.transactions) == 1


@pytest.mark.asyncio
async def test_two_incoming_transfers_preserve_both_credits(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    system = build_system(
        payment_harness_factory,
        initial_state=application_state_factory(
            {"S1": Decimal("100.00"), "S2": Decimal("100.00"), "R": Decimal("20.00")}
        ),
    )
    results = await asyncio.wait_for(
        asyncio.gather(
            system.orchestrator.handle(
                "transferMoney sender_id=S1 receiver_id=R amount=100.00",
                idempotency_key="IDEMP-IN-1",
                requested_at=NOW,
            ),
            system.orchestrator.handle(
                "transferMoney sender_id=S2 receiver_id=R amount=100.00",
                idempotency_key="IDEMP-IN-2",
                requested_at=NOW,
            ),
        ),
        timeout=2.0,
    )

    assert all(result.agent_name == "OrchestratorAgent" for result in results)
    assert system.payment.manager.current_state.wallets["R"].balance == Decimal("220.00")


@pytest.mark.asyncio
async def test_opposite_transfers_finish_without_deadlock(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    system = build_system(
        payment_harness_factory,
        initial_state=application_state_factory({"U1": Decimal("100.00"), "U2": Decimal("100.00")}),
    )
    results = await asyncio.wait_for(
        asyncio.gather(
            system.orchestrator.handle(
                "transferMoney sender_id=U1 receiver_id=U2 amount=10.00",
                idempotency_key="IDEMP-OP-1",
                requested_at=NOW,
            ),
            system.orchestrator.handle(
                "transferMoney sender_id=U2 receiver_id=U1 amount=10.00",
                idempotency_key="IDEMP-OP-2",
                requested_at=NOW,
            ),
        ),
        timeout=2.0,
    )

    assert all(result.agent_name == "OrchestratorAgent" for result in results)
    assert system.payment.manager.current_state.wallets["U1"].balance == Decimal("100.00")
    assert system.payment.manager.current_state.wallets["U2"].balance == Decimal("100.00")


@pytest.mark.asyncio
async def test_same_request_and_idempotency_key_has_one_logical_transaction(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    system = build_system(
        payment_harness_factory,
        initial_state=application_state_factory({"S": Decimal("100.00"), "R": Decimal("0.00")}),
    )
    command = "transferMoney sender_id=S receiver_id=R amount=10.00"
    results = await asyncio.wait_for(
        asyncio.gather(
            system.orchestrator.handle(
                command,
                idempotency_key="IDEMP-CONCURRENT-SAME",
                requested_at=NOW,
            ),
            system.orchestrator.handle(
                command,
                idempotency_key="IDEMP-CONCURRENT-SAME",
                requested_at=NOW,
            ),
        ),
        timeout=2.0,
    )

    assert results[0].output["transaction_id"] == results[1].output["transaction_id"]
    assert len(system.payment.manager.current_state.transactions) == 1
    assert system.payment.manager.current_state.wallets["S"].balance == Decimal("90.00")


@pytest.mark.asyncio
async def test_concurrent_approval_creates_one_transaction(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    system = build_system(
        payment_harness_factory,
        initial_state=application_state_factory(
            {"REQUESTER": Decimal("0.00"), "PAYER": Decimal("100.00")}
        ),
    )
    pending = await system.orchestrator.handle(
        "requestPayment requester_id=REQUESTER payer_id=PAYER amount=20.00",
        idempotency_key="IDEMP-CONCURRENT-REQ",
        requested_at=NOW,
    )
    command = f"approvePayment request_id={pending.output['payment_request_id']}"
    results = await asyncio.wait_for(
        asyncio.gather(
            system.orchestrator.handle(
                command,
                idempotency_key="IDEMP-CONCURRENT-APPROVE-1",
                requested_at=NOW,
            ),
            system.orchestrator.handle(
                command,
                idempotency_key="IDEMP-CONCURRENT-APPROVE-2",
                requested_at=NOW,
            ),
        ),
        timeout=2.0,
    )

    assert sorted(result.agent_name for result in results) == [
        "OrchestratorAgent",
        "ReflectionAgent",
    ]
    assert len(system.payment.manager.current_state.transactions) == 1
    assert system.payment.manager.current_state.wallets["PAYER"].balance == Decimal("80.00")
