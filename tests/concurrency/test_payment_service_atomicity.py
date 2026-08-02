"""Repository-failure atomicity tests for PaymentDomainService."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_save_failure_exposes_no_business_idempotency_or_audit_state(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("0.00")}
        )
    )
    harness.repository.fail_next = True

    with pytest.raises(OSError, match="configured save failure"):
        await harness.service.transfer_money(
            sender_id="SENDER",
            receiver_id="RECEIVER",
            amount=Decimal("10.00"),
            idempotency_key="IDEMP-FAILED",
            correlation_id="CORR-FAILED",
        )

    state = harness.manager.current_state
    assert state.wallets["SENDER"].balance == Decimal("100.00")
    assert state.wallets["RECEIVER"].balance == Decimal("0.00")
    assert state.transactions == {}
    assert state.idempotency_records == {}
    assert state.pending_audit_events == {}


@pytest.mark.asyncio
async def test_later_operation_succeeds_after_save_failure(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("0.00")}
        )
    )
    harness.repository.fail_next = True
    with pytest.raises(OSError):
        await harness.service.transfer_money(
            sender_id="SENDER",
            receiver_id="RECEIVER",
            amount=Decimal("10.00"),
            idempotency_key="IDEMP-FAILED",
            correlation_id="CORR-FAILED",
        )

    snapshot = await harness.service.transfer_money(
        sender_id="SENDER",
        receiver_id="RECEIVER",
        amount=Decimal("10.00"),
        idempotency_key="IDEMP-RECOVERED",
        correlation_id="CORR-RECOVERED",
    )

    state = harness.manager.current_state
    assert snapshot.transaction.transaction_id in state.transactions
    assert state.wallets["SENDER"].balance == Decimal("90.00")
    assert "IDEMP-RECOVERED" in state.idempotency_records
    assert len(state.pending_audit_events) == 1
