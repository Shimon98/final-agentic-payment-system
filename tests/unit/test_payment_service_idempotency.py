"""Exact-result idempotency tests across payment-service operations."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from agentic_payments.domain import (
    IdempotencyConflictError,
    RiskLevel,
    StateInvariantError,
)


@pytest.mark.asyncio
async def test_logically_equal_normalized_phone_reuses_create_result(
    payment_harness_factory: Any,
) -> None:
    harness = payment_harness_factory()

    first = await harness.service.create_user(
        name="Alice",
        phone_number="+972-50-123-4567",
        initial_balance=Decimal("10.00"),
        idempotency_key="IDEMP-NORMALIZED",
        correlation_id="CORR-FIRST",
    )
    second = await harness.service.create_user(
        name="Alice",
        phone_number="+972 (50) 123 4567",
        initial_balance=Decimal("10.00"),
        idempotency_key="IDEMP-NORMALIZED",
        correlation_id="CORR-SECOND",
    )

    assert second == first
    assert harness.repository.save_calls == 1


@pytest.mark.asyncio
async def test_same_key_across_different_operations_conflicts(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"REQUESTER": Decimal("10.00"), "PAYER": Decimal("10.00")}
        )
    )
    await harness.service.create_user(
        name="Created",
        phone_number="0501234567",
        initial_balance=Decimal("1.00"),
        idempotency_key="IDEMP-SHARED",
        correlation_id="CORR-CREATE",
    )

    with pytest.raises(IdempotencyConflictError):
        await harness.service.request_payment(
            requester_id="REQUESTER",
            payer_id="PAYER",
            amount=Decimal("1.00"),
            idempotency_key="IDEMP-SHARED",
            correlation_id="CORR-REQUEST",
        )


@pytest.mark.asyncio
async def test_missing_success_payload_raises_state_invariant(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("0.00")}
        )
    )
    arguments = {
        "sender_id": "SENDER",
        "receiver_id": "RECEIVER",
        "amount": Decimal("10.00"),
        "idempotency_key": "IDEMP-TRANSFER",
        "correlation_id": "CORR-TRANSFER",
    }
    await harness.service.transfer_money(**arguments)
    record = harness.manager._state.idempotency_records["IDEMP-TRANSFER"]
    harness.manager._state.idempotency_records["IDEMP-TRANSFER"] = replace(
        record,
        result_payload=None,
    )

    with pytest.raises(StateInvariantError, match="no result payload"):
        await harness.service.transfer_money(**arguments)

    assert harness.repository.save_calls == 1


@pytest.mark.asyncio
async def test_unknown_result_type_marker_raises_state_invariant(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("0.00")}
        )
    )
    arguments = {
        "sender_id": "SENDER",
        "receiver_id": "RECEIVER",
        "amount": Decimal("10.00"),
        "idempotency_key": "IDEMP-TRANSFER",
        "correlation_id": "CORR-TRANSFER",
    }
    await harness.service.transfer_money(**arguments)
    record = harness.manager._state.idempotency_records["IDEMP-TRANSFER"]
    harness.manager._state.idempotency_records["IDEMP-TRANSFER"] = replace(
        record,
        result_payload={"result_type": "Unknown", "snapshot": {}},
    )

    with pytest.raises(StateInvariantError, match="result type"):
        await harness.service.transfer_money(**arguments)


@pytest.mark.asyncio
async def test_idempotent_retry_does_not_generate_or_save(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("0.00")}
        )
    )
    arguments = {
        "sender_id": "SENDER",
        "receiver_id": "RECEIVER",
        "amount": Decimal("10.00"),
        "idempotency_key": "IDEMP-TRANSFER",
        "correlation_id": "CORR-TRANSFER",
    }
    first = await harness.service.transfer_money(**arguments)
    counts = (
        harness.ids.transaction_calls,
        harness.ids.audit_event_calls,
        harness.clock.calls,
        harness.repository.save_calls,
    )

    second = await harness.service.transfer_money(**arguments)

    assert second == first
    assert (
        harness.ids.transaction_calls,
        harness.ids.audit_event_calls,
        harness.clock.calls,
        harness.repository.save_calls,
    ) == counts


@pytest.mark.asyncio
async def test_risk_annotation_retry_returns_exact_original(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("0.00")}
        )
    )
    snapshot = await harness.service.transfer_money(
        sender_id="SENDER",
        receiver_id="RECEIVER",
        amount=Decimal("10.00"),
        idempotency_key="IDEMP-TRANSFER",
        correlation_id="CORR-TRANSFER",
    )
    arguments = {
        "transaction_id": snapshot.transaction.transaction_id,
        "score": 80,
        "level": RiskLevel.HIGH,
        "reasons": ["large", "rapid"],
        "flagged": True,
        "idempotency_key": "IDEMP-RISK",
        "correlation_id": "CORR-RISK",
    }

    first = await harness.service.annotate_transaction_risk(**arguments)
    save_calls = harness.repository.save_calls
    second = await harness.service.annotate_transaction_risk(**arguments)

    assert second == first
    assert harness.repository.save_calls == save_calls


@pytest.mark.asyncio
async def test_risk_reason_order_is_part_of_fingerprint(
    payment_harness_factory: Any,
    application_state_factory: Any,
) -> None:
    harness = payment_harness_factory(
        initial_state=application_state_factory(
            {"SENDER": Decimal("100.00"), "RECEIVER": Decimal("0.00")}
        )
    )
    snapshot = await harness.service.transfer_money(
        sender_id="SENDER",
        receiver_id="RECEIVER",
        amount=Decimal("10.00"),
        idempotency_key="IDEMP-TRANSFER",
        correlation_id="CORR-TRANSFER",
    )
    base = {
        "transaction_id": snapshot.transaction.transaction_id,
        "score": 80,
        "level": RiskLevel.HIGH,
        "flagged": True,
        "idempotency_key": "IDEMP-RISK",
        "correlation_id": "CORR-RISK",
    }
    await harness.service.annotate_transaction_risk(reasons=["large", "rapid"], **base)

    with pytest.raises(IdempotencyConflictError):
        await harness.service.annotate_transaction_risk(reasons=["rapid", "large"], **base)
