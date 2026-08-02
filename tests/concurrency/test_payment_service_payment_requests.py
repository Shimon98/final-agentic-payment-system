"""Concurrent payment-request approval tests."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest
from conftest import FIXED_TIME

from agentic_payments.domain import (
    PaymentRequest,
    PaymentRequestAlreadyResolvedError,
    PaymentRequestStatus,
)


def _pending_state(application_state_factory: Any) -> Any:
    state = application_state_factory({"REQUESTER": Decimal("0.00"), "PAYER": Decimal("100.00")})
    state.payment_requests["REQ-1"] = PaymentRequest(
        request_id="REQ-1",
        requester_id="REQUESTER",
        payer_id="PAYER",
        amount=Decimal("25.00"),
        status=PaymentRequestStatus.PENDING,
        created_at=FIXED_TIME,
        resolved_at=None,
        related_transaction_id=None,
        correlation_id="CORR-REQUEST",
    )
    return state


@pytest.mark.asyncio
async def test_concurrent_approval_with_different_keys_creates_one_transaction(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(initial_state=_pending_state(application_state_factory))
    start = asyncio.Event()

    async def approve(key: str) -> tuple[Any, Any]:
        await start.wait()
        return await harness.service.approve_payment_request(
            request_id="REQ-1",
            idempotency_key=key,
            correlation_id=f"CORR-{key}",
        )

    tasks = [
        asyncio.create_task(approve("IDEMP-A")),
        asyncio.create_task(approve("IDEMP-B")),
    ]
    start.set()
    results = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=True),
        timeout=1.0,
    )

    assert sum(isinstance(result, tuple) for result in results) == 1
    assert sum(isinstance(result, PaymentRequestAlreadyResolvedError) for result in results) == 1
    state = harness.manager.current_state
    assert len(state.transactions) == 1
    assert state.payment_requests["REQ-1"].status is PaymentRequestStatus.APPROVED
    assert len(state.idempotency_records) == 1
    assert len(state.pending_audit_events) == 2


@pytest.mark.asyncio
async def test_concurrent_approval_same_key_returns_same_exact_result(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(initial_state=_pending_state(application_state_factory))
    start = asyncio.Event()

    async def approve() -> tuple[Any, Any]:
        await start.wait()
        return await harness.service.approve_payment_request(
            request_id="REQ-1",
            idempotency_key="IDEMP-SAME",
            correlation_id="CORR-SAME",
        )

    tasks = [asyncio.create_task(approve()), asyncio.create_task(approve())]
    start.set()
    first, second = await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)

    assert second == first
    assert harness.repository.save_calls == 1
    assert len(harness.manager.current_state.transactions) == 1
